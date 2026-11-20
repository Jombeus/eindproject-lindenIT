import logging
import os
import random
import signal
import sys
import time
from functools import wraps

import psycopg2
import psycopg2.extras
from flask import (Flask, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

# ---------- logging ----------
LOG_DIR = os.environ.get("LOG_DIR", "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.addLevelName(logging.WARNING, "WARN")  # zelfde notatie als in de opdracht
formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s",
                              "%Y-%m-%d %H:%M:%S")
logger = logging.getLogger("gridwatch")
logger.setLevel(logging.INFO)
for handler in (logging.FileHandler(os.path.join(LOG_DIR, "app.log")),
                logging.StreamHandler(sys.stdout)):  # ook zichtbaar via docker logs
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# ---------- app en database ----------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-key")

DB_CONFIG = dict(
    host=os.environ.get("DB_HOST", "db"),
    port=os.environ.get("DB_PORT", "5432"),
    dbname=os.environ.get("DB_NAME", "gridwatch"),
    user=os.environ.get("DB_USER", "gridwatch"),
    password=os.environ.get("DB_PASSWORD", "gridwatch_pw"),
)


def get_db():
    """Eén databaseverbinding per request."""
    if "db" not in g:
        try:
            g.db = psycopg2.connect(**DB_CONFIG, connect_timeout=3)
        except psycopg2.OperationalError:
            logger.error("Database connection failed")
            raise
    return g.db


def query(sql, params=(), one=False, commit=False):
    """Voer een SQL-query uit en geef de rijen terug als dictionaries."""
    cur = get_db().cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(sql, params)
    result = None
    if cur.description:
        result = cur.fetchone() if one else cur.fetchall()
    if commit:
        g.db.commit()
    cur.close()
    return result


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def client_ip():
    return request.remote_addr


# ---------- API-verzoeken en fouten loggen ----------
@app.before_request
def start_timer():
    g.start = time.time()


@app.after_request
def log_api_request(response):
    if request.path.startswith("/api/"):
        ms = int((time.time() - g.start) * 1000)
        logger.info("%s %s from %s status=%s %sms",
                    request.method, request.path, client_ip(),
                    response.status_code, ms)
    return response


@app.errorhandler(Exception)
def handle_error(exc):
    # HTTP-fouten zoals 404 horen niet als ERROR in het log
    if hasattr(exc, "code") and exc.code and exc.code < 500:
        logger.warning("HTTP %s on %s from %s", exc.code, request.path, client_ip())
        return exc
    logger.error("Unhandled exception on %s: %s", request.path, exc)
    if request.path.startswith("/api/"):
        return jsonify(error="interne fout"), 500
    return render_template("error.html"), 500


def login_required(view):
    """Zet @login_required boven een pagina die alleen voor ingelogde gebruikers is."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


# ---------- webpagina's ----------
@app.route("/")
def index():
    return redirect(url_for("stations") if "user" in session else url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        user = query("SELECT * FROM users WHERE username = %s", (username,), one=True)
        if user and check_password_hash(user["password"], password):
            session["user"] = user["username"]
            session["role"] = user["role"]
            logger.info("User %s logged in from %s", username, client_ip())
            return redirect(url_for("stations"))
        logger.warning("Invalid password for user %s from %s", username, client_ip())
        if "X-Scenario" not in request.headers:  # scenario 2-knop: alleen loggen
            flash("Ongeldige gebruikersnaam of wachtwoord.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    user = session.pop("user", None)
    session.pop("role", None)
    if user:
        logger.info("User %s logged out", user)
    return redirect(url_for("login"))


@app.route("/stations")
@login_required
def stations():
    rows = query("""SELECT s.*, d.vermogen_mw, d.temperatuur
                    FROM stations s
                    LEFT JOIN LATERAL (SELECT * FROM sensor_data
                                       WHERE station_id = s.id
                                       ORDER BY tijdstip DESC, id DESC LIMIT 1) d ON TRUE
                    ORDER BY s.id""")
    return render_template("stations.html", stations=rows)


@app.route("/meldingen", methods=["GET", "POST"])
@login_required
def meldingen():
    if request.method == "POST":
        station_id = request.form.get("station_id")
        mtype = request.form.get("type")
        beschrijving = request.form.get("beschrijving", "").strip()
        if not beschrijving:
            flash("Vul een beschrijving in.")
        else:
            query("""INSERT INTO alerts (station_id, type, beschrijving, ingediend_door)
                     VALUES (%s, %s, %s, %s)""",
                  (station_id, mtype, beschrijving, session["user"]), commit=True)
            query("INSERT INTO events (type, beschrijving) VALUES (%s, %s)",
                  ("MELDING", f"{mtype} gemeld door {session['user']}: {beschrijving}"),
                  commit=True)
            logger.info("New %s report by %s for station %s", mtype,
                        session["user"], station_id)
            flash("Melding opgeslagen.")
        return redirect(url_for("meldingen"))
    alerts = query("""SELECT a.*, s.naam FROM alerts a
                      JOIN stations s ON s.id = a.station_id
                      ORDER BY a.tijdstip DESC""")
    stations_list = query("SELECT id, naam FROM stations ORDER BY id")
    return render_template("meldingen.html", alerts=alerts, stations=stations_list)


@app.route("/scenarios")
@login_required
def scenarios():
    return render_template("scenarios.html")


# ---------- API ----------
@app.route("/api/stations")
def api_stations():
    rows = query("SELECT id, naam, locatie, status FROM stations ORDER BY id")
    return jsonify(rows)


@app.route("/api/station/<int:station_id>")
def api_station(station_id):
    row = query("""SELECT s.id, s.naam AS station, s.locatie, s.status,
                          d.vermogen_mw, d.temperatuur, d.tijdstip
                   FROM stations s
                   LEFT JOIN LATERAL (SELECT * FROM sensor_data WHERE station_id = s.id
                                      ORDER BY tijdstip DESC, id DESC LIMIT 1) d ON TRUE
                   WHERE s.id = %s""", (station_id,), one=True)
    if not row:
        return jsonify(error="station niet gevonden"), 404
    row["vermogen_mw"] = float(row["vermogen_mw"]) if row["vermogen_mw"] is not None else None
    row["temperatuur"] = float(row["temperatuur"]) if row["temperatuur"] is not None else None
    row["tijdstip"] = row["tijdstip"].isoformat() if row["tijdstip"] else None
    return jsonify(row)


@app.route("/api/alerts")
def api_alerts():
    rows = query("""SELECT a.id, s.naam AS station, a.type, a.beschrijving, a.tijdstip
                    FROM alerts a JOIN stations s ON s.id = a.station_id
                    ORDER BY a.tijdstip DESC""")
    for r in rows:
        r["tijdstip"] = r["tijdstip"].isoformat()
    return jsonify(rows)


@app.route("/api/sensor-data")
def api_sensor_data():
    limit = min(request.args.get("limit", 20, type=int), 500)
    rows = query("""SELECT s.naam AS station, d.vermogen_mw, d.temperatuur, d.tijdstip
                    FROM sensor_data d JOIN stations s ON s.id = d.station_id
                    ORDER BY d.tijdstip DESC, d.id DESC LIMIT %s""", (limit,))
    for r in rows:
        r["vermogen_mw"] = float(r["vermogen_mw"])
        r["temperatuur"] = float(r["temperatuur"])
        r["tijdstip"] = r["tijdstip"].isoformat()
    return jsonify(rows)


@app.route("/api/grid-health")
def api_grid_health():
    """Bonus: samenvatting van de netstatus."""
    s = query("""SELECT
                   COUNT(*) FILTER (WHERE status IN ('OK','ONDERHOUD')) AS online,
                   COUNT(*) FILTER (WHERE status = 'OFFLINE') AS offline,
                   COUNT(*) FILTER (WHERE status = 'STORING') AS storingen
                 FROM stations""", one=True)
    status = "WAARSCHUWING" if (s["offline"] or s["storingen"]) else "OK"
    return jsonify(stations_online=s["online"], stations_offline=s["offline"],
                   storingen=s["storingen"], status=status)


# ---------- scenario's ----------
@app.route("/scenarios/fout", methods=["POST"])
@login_required
def scenario_fout():
    """Scenario: applicatiefout genereren."""
    logger.error("Test exception generated by %s", session["user"])
    query("INSERT INTO events (type, beschrijving) VALUES ('FOUT', 'Test exception generated')",
          commit=True)
    flash("Er is een testfout gelogd (ERROR).")
    return redirect(url_for("scenarios"))


@app.route("/scenarios/belasting", methods=["POST"])
@login_required
def scenario_belasting():
    """Extra scenario: hoge belasting, 1000 sensorrecords genereren."""
    aantal = 1000
    start = time.time()
    logger.info("Generating %s sensor records (requested by %s)", aantal, session["user"])
    ids = [r["id"] for r in query("SELECT id FROM stations")]
    for i in range(aantal):
        # Bewust record voor record: levert database-activiteit en CPU-gebruik op
        query("INSERT INTO sensor_data (station_id, vermogen_mw, temperatuur) VALUES (%s,%s,%s)",
              (random.choice(ids), round(random.uniform(0, 400), 2),
               round(random.uniform(15, 95), 1)))
        sum(x * x for x in range(2000))  # wat extra rekenwerk voor CPU-verbruik
        if (i + 1) % 250 == 0:
            logger.info("Generated %s/%s sensor records", i + 1, aantal)
    g.db.commit()
    query("INSERT INTO events (type, beschrijving) VALUES ('BELASTING', %s)",
          (f"{aantal} sensorrecords gegenereerd",), commit=True)
    logger.info("Finished generating %s sensor records in %.1fs", aantal, time.time() - start)
    flash(f"{aantal} sensorrecords gegenereerd.")
    return redirect(url_for("scenarios"))


@app.route("/health")
def health():
    return "ok"


# ---------- starten, stoppen en gebruikers aanmaken ----------
def wait_for_db_and_seed():
    """Wacht tot de database klaar is en maak de gebruikers aan."""
    for poging in range(1, 11):
        try:
            conn = psycopg2.connect(**DB_CONFIG, connect_timeout=3)
            break
        except psycopg2.OperationalError:
            logger.error("Database connection failed (attempt %s/10)", poging)
            time.sleep(3)
    else:
        logger.error("Giving up: database not reachable")
        sys.exit(1)

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        for name, pw, role in [("admin", "Welkom2026!", "admin"),
                               ("operator", "Operator2026!", "operator"),
                               ("viewer", "Viewer2026!", "viewer")]:
            cur.execute("INSERT INTO users (username, password, role) VALUES (%s,%s,%s)",
                        (name, generate_password_hash(pw), role))
        conn.commit()
        logger.info("Seeded default users")
    conn.close()


def on_stop(signum, _frame):
    # 'docker stop' stuurt het signaal SIGTERM
    logger.info("Application stopped (signal %s)", signum)
    logging.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, on_stop)
    signal.signal(signal.SIGINT, on_stop)
    wait_for_db_and_seed()
    logger.info("Application started")
    app.run(host="0.0.0.0", port=5000, threaded=True)
