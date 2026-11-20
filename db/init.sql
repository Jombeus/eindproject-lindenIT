CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'viewer'
);

CREATE TABLE IF NOT EXISTS stations (
    id SERIAL PRIMARY KEY,
    naam VARCHAR(100) NOT NULL,
    locatie VARCHAR(100) NOT NULL,
    status VARCHAR(30) NOT NULL
);

CREATE TABLE IF NOT EXISTS sensor_data (
    id SERIAL PRIMARY KEY,
    station_id INTEGER REFERENCES stations(id),
    tijdstip TIMESTAMP NOT NULL DEFAULT NOW(),
    vermogen_mw NUMERIC(7,2) NOT NULL,
    temperatuur NUMERIC(5,1) NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id SERIAL PRIMARY KEY,
    station_id INTEGER REFERENCES stations(id),
    tijdstip TIMESTAMP NOT NULL DEFAULT NOW(),
    type VARCHAR(30) NOT NULL,
    beschrijving TEXT NOT NULL,
    ingediend_door VARCHAR(50)
);

CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    tijdstip TIMESTAMP NOT NULL DEFAULT NOW(),
    type VARCHAR(30) NOT NULL,
    beschrijving TEXT NOT NULL
);

INSERT INTO stations (naam, locatie, status) VALUES
    ('Station Arnhem', 'Arnhem', 'OK'),
    ('Station Zwolle', 'Zwolle', 'ONDERHOUD'),
    ('Station Eemshaven', 'Eemshaven', 'STORING'),
    ('Station Utrecht', 'Utrecht', 'OK'),
    ('Station Maasvlakte', 'Rotterdam', 'OFFLINE');

INSERT INTO sensor_data (station_id, vermogen_mw, temperatuur) VALUES
    (1, 220, 34), (2, 0, 21), (3, 95, 78), (4, 180, 31), (5, 0, 18);

INSERT INTO alerts (station_id, type, beschrijving, ingediend_door) VALUES
    (2, 'ONDERHOUD', 'Onderhoud gepland: vervangen schakelmateriaal', 'admin'),
    (3, 'STORING', 'Actieve storing: oververhitting transformator', 'admin');
