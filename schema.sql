PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS bowlers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  bix_group TEXT NOT NULL CHECK (bix_group IN ('A','B'))
);
CREATE TABLE IF NOT EXISTS alleys (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bowler_id INTEGER NOT NULL,
  alley_id INTEGER NOT NULL,
  session_date TEXT NOT NULL,
  CONSTRAINT unique_bowler_date UNIQUE (bowler_id, session_date),
  FOREIGN KEY (bowler_id) REFERENCES bowlers(id) ON DELETE CASCADE,
  FOREIGN KEY (alley_id)  REFERENCES alleys(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS games (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL,
  game_number INTEGER NOT NULL,
  score INTEGER NOT NULL CHECK (score BETWEEN 1 AND 300),
  UNIQUE(session_id, game_number),
  FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

INSERT OR IGNORE INTO bowlers (name, bix_group) VALUES
('Rajan', 'A'),
('Medina', 'A'),
('Barsotti', 'B'),
('Baule', 'B');

INSERT OR IGNORE INTO alleys (name) VALUES
('Hazel Dell Lanes'),
('King Pins Beaverton'),
('Lilac Lanes'),
('Milwaukie Lanes'),
('North Bowl'),
('Sunset Bowling Center'),
('Valley Bowl'),
('Zodos Lanes');