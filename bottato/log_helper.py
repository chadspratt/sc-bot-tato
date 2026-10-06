import os
import sqlite3
from loguru import logger
from typing import Any, Dict, List

from sc2.bot_ai import BotAI
from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId

# Try to import pymysql - it will be available in local testing, not on server
try:
    import pymysql
    PYMYSQL_AVAILABLE = True
except ImportError:
    PYMYSQL_AVAILABLE = False


class LogHelper:
    previous_messages: dict[str, int] = {}
    new_messages: List[str] = []
    chat_messages: List[str] = []
    db_messages: List[str] = []

    bot: BotAI
    enemy_race: Race | None = None

    testing: bool = False
    test_match_id: int | None = None
    use_mariadb: bool = False
    scouting_db: str = ""
    last_scouting_log: float = 0.0

    @staticmethod
    def init(bot: BotAI):
        LogHelper.bot = bot
        match_id = os.environ.get("TEST_MATCH_ID")
        if match_id is not None:
            LogHelper.test_match_id = int(match_id)
        # Use MariaDB only if pymysql is available AND we're in local testing mode
        LogHelper.use_mariadb = PYMYSQL_AVAILABLE and LogHelper.test_match_id is not None
        LogHelper.add_log(f"LogHelper initialized. Test Match ID: {LogHelper.test_match_id}, Using MariaDB: {LogHelper.use_mariadb}")
        # LogHelper.scouting_db = "../db/match_data.db" if LogHelper.testing else "./logs/match_data.db"
        LogHelper.scouting_db = "../db/match_data.db" if LogHelper.testing else "/logs/BotTato/match_data.db"
        # enable writing to an sqlite db on the ladder
        # if not LogHelper.use_mariadb:
        #     LogHelper.test_match_id = 0

    @staticmethod
    def add_log(message: str):
        if LogHelper.testing:
            return
        if message not in LogHelper.new_messages:
            LogHelper.new_messages.append(message)

    @staticmethod
    async def add_chat(message: str):
        if LogHelper.testing:
            return
        if message not in LogHelper.chat_messages:
            await LogHelper.bot.client.chat_send(message, False)
            LogHelper.chat_messages.append(message)
        if message not in LogHelper.new_messages:
            LogHelper.new_messages.append(message)

    @staticmethod
    def print_logs(iteration: int):
        if LogHelper.testing:
            return
        formatted_time = LogHelper.bot.time_formatted

        to_delete = []
        for message in LogHelper.previous_messages:
            if message not in LogHelper.new_messages:
                to_delete.append(message)
                if LogHelper.previous_messages[message] > 1:
                    logger.info(f"{iteration} - {formatted_time}: ended ({LogHelper.previous_messages[message]}x): {message}")
        for message in to_delete:
            del LogHelper.previous_messages[message]

        for message in LogHelper.new_messages:
            if message not in LogHelper.previous_messages:
                logger.info(f"{iteration} - {formatted_time}: {message}")
                LogHelper.previous_messages[message] = 1
            else:
                LogHelper.previous_messages[message] += 1
        LogHelper.new_messages = []

    @staticmethod
    def log_to_db(type: str, message: str, override_time: float | None = None):
        """Update the match duration in the database if we're in testing mode."""
        LogHelper.add_log(message)
        if LogHelper.test_match_id is None:
            LogHelper.add_log("no test match id, skipping db logging")
            return
        # if message not in LogHelper.db_messages:
        LogHelper.db_messages.append(message)
        
        timestamp = override_time if override_time else LogHelper.bot.time
        
        if LogHelper.use_mariadb:
            LogHelper.add_log("logging to mariadb")
            # Use MariaDB for local testing
            conn = pymysql.connect( # type: ignore always defined if USE_MARIADB is True
                host=os.environ.get('DB_HOST', 'localhost'),
                port=int(os.environ.get('DB_PORT', '3306')),
                user=os.environ.get('DB_USER', 'root'),
                password=os.environ.get('DB_PASSWORD', 'default'),
                database=os.environ.get('DB_NAME', 'sc_bot'),
                autocommit=False
            )
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO match_event (match_id, type, message, game_timestamp)
                VALUES (%s, %s, %s, %s)
            ''', (int(LogHelper.test_match_id), type, message, timestamp))
            if type == "Match ended":
                cursor.execute('''
                    UPDATE `match` SET duration_in_game_time = %s
                    WHERE id = %s
                ''', (int(timestamp), LogHelper.test_match_id))
                conn.commit()
        else:
            LogHelper.add_log("logging to sqlite")
            # Use SQLite for server matches
            conn = sqlite3.connect('../db/match_data.db')
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO match_event (match_id, type, message, game_timestamp)
                VALUES (?, ?, ?, ?)
            ''', (LogHelper.test_match_id, type, message, timestamp))
        
        conn.commit()
        conn.close()

    excluded_types = [
        UnitTypeId.AUTOTURRET,
        UnitTypeId.REACTOR,
        UnitTypeId.TECHLAB,
        UnitTypeId.EGG,
        UnitTypeId.CREEPTUMOR,
        UnitTypeId.CREEPTUMORBURROWED,
        UnitTypeId.CREEPTUMORQUEEN,
        UnitTypeId.BANELINGCOCOON,
        UnitTypeId.RAVAGERCOCOON,
        UnitTypeId.OVERLORDCOCOON,
        UnitTypeId.TRANSPORTOVERLORDCOCOON,
        UnitTypeId.BROODLORDCOCOON,
        UnitTypeId.CHANGELING,
        UnitTypeId.BROODLING,
        UnitTypeId.INTERCEPTOR
    ]
    @staticmethod
    def log_scouting_to_sqlite(timestamp: float, data: Dict[UnitTypeId, int]):
        for type_to_exclude in LogHelper.excluded_types:
            if type_to_exclude in data:
                del data[type_to_exclude]
        if len(data) == 0 or LogHelper.enemy_race is None:
            return

        try:
            LogHelper.add_log(f"logging to sqlite at {LogHelper.scouting_db}")
            conn = sqlite3.connect(LogHelper.scouting_db)
        except sqlite3.OperationalError:
            LogHelper.scouting_db = f'/root/replays/{LogHelper.test_match_id}.db'
            LogHelper.add_log(f"logging to sqlite at {LogHelper.scouting_db}")
            try:
                conn = sqlite3.connect(LogHelper.scouting_db)
            except sqlite3.OperationalError:
                LogHelper.scouting_db = f'./logs/match_data.db'
                LogHelper.add_log(f"logging to sqlite at {LogHelper.scouting_db}")
                conn = sqlite3.connect(LogHelper.scouting_db)
        if LogHelper.init_sqlite_table("scouting", conn, LogHelper.enemy_race):
            table = "scouting_" + LogHelper.enemy_race.name.lower()
            cursor = conn.cursor()
            columns = 'game_timestamp, ' + ', '.join([key.name.lower() for key in data.keys()])
            placeholders = ', '.join('?' for _ in data)
            cursor.execute(f'''
                INSERT INTO {table} ({columns})
                VALUES (?, {placeholders})
            ''', (timestamp, *data.values()))
            conn.commit()
            LogHelper.add_log("logged to sqlite")
            LogHelper.last_scouting_log = timestamp
        conn.close()

    initialized_tables: set[str] = set()
    @staticmethod
    def init_sqlite_table(table: str, conn: sqlite3.Connection, race: Race) -> bool:
        if table in LogHelper.initialized_tables:
            return True
        if table == "scouting":
            LogHelper.initialize_scouting_table(conn, race)
            return True
        return False

    @staticmethod
    def initialize_scouting_table(conn: sqlite3.Connection, race: Race):
        cursor = conn.cursor()
        unit_columns = ', '.join([f'{unit.name.lower()} INTEGER DEFAULT 0' for unit in LogHelper.scouting_row_order[race]])
        table_name = "scouting_" + race.name.lower()
        LogHelper.add_log(f"initializing sqlite table {table_name}")
        cursor.execute(f'''
            DROP TABLE IF EXISTS {table_name}
        ''')
        cursor.execute(f'''
            CREATE TABLE {table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id INTEGER DEFAULT 0,
                game_timestamp REAL,
                {unit_columns}
            )
        ''')
        LogHelper.initialized_tables.add("scouting")

    scouting_row_order: Dict[Race, List[UnitTypeId]] = {
        Race.Protoss: [
            UnitTypeId.PROBE,
            UnitTypeId.ZEALOT,
            UnitTypeId.STALKER,
            UnitTypeId.SENTRY,
            UnitTypeId.ADEPT,
            UnitTypeId.ADEPTPHASESHIFT,
            UnitTypeId.HIGHTEMPLAR,
            UnitTypeId.DARKTEMPLAR,
            UnitTypeId.ARCHON,
            UnitTypeId.OBSERVER,
            UnitTypeId.WARPPRISM,
            UnitTypeId.IMMORTAL,
            UnitTypeId.COLOSSUS,
            UnitTypeId.DISRUPTOR,
            UnitTypeId.PHOENIX,
            UnitTypeId.VOIDRAY,
            UnitTypeId.ORACLE,
            UnitTypeId.TEMPEST,
            UnitTypeId.CARRIER,
            UnitTypeId.MOTHERSHIP,
            UnitTypeId.PYLON,
            UnitTypeId.NEXUS,
            UnitTypeId.ASSIMILATOR,
            UnitTypeId.GATEWAY,
            UnitTypeId.WARPGATE,
            UnitTypeId.FORGE,
            UnitTypeId.CYBERNETICSCORE,
            UnitTypeId.ROBOTICSFACILITY,
            UnitTypeId.STARGATE,
            UnitTypeId.TWILIGHTCOUNCIL,
            UnitTypeId.ROBOTICSBAY,
            UnitTypeId.FLEETBEACON,
            UnitTypeId.TEMPLARARCHIVE,
            UnitTypeId.DARKSHRINE,
            UnitTypeId.PHOTONCANNON,
            UnitTypeId.SHIELDBATTERY,
        ],
        Race.Terran: [
            UnitTypeId.SCV,
            UnitTypeId.MARINE,
            UnitTypeId.REAPER,
            UnitTypeId.MARAUDER,
            UnitTypeId.GHOST,
            UnitTypeId.HELLION,
            UnitTypeId.HELLIONTANK,
            UnitTypeId.WIDOWMINE,
            UnitTypeId.CYCLONE,
            UnitTypeId.SIEGETANK,
            UnitTypeId.THOR,
            UnitTypeId.VIKINGFIGHTER,
            UnitTypeId.MEDIVAC,
            UnitTypeId.LIBERATOR,
            UnitTypeId.RAVEN,
            UnitTypeId.BANSHEE,
            UnitTypeId.BATTLECRUISER,
            UnitTypeId.COMMANDCENTER,
            UnitTypeId.ORBITALCOMMAND,
            UnitTypeId.PLANETARYFORTRESS,
            UnitTypeId.SUPPLYDEPOT,
            UnitTypeId.REFINERY,
            UnitTypeId.BARRACKS,
            UnitTypeId.FACTORY,
            UnitTypeId.STARPORT,
            UnitTypeId.GHOSTACADEMY,
            UnitTypeId.ENGINEERINGBAY,
            UnitTypeId.ARMORY,
            UnitTypeId.FUSIONCORE,
            UnitTypeId.BUNKER,
            UnitTypeId.MISSILETURRET,
            UnitTypeId.SENSORTOWER,
            UnitTypeId.BARRACKSREACTOR,
            UnitTypeId.BARRACKSTECHLAB,
            UnitTypeId.FACTORYREACTOR,
            UnitTypeId.FACTORYTECHLAB,
            UnitTypeId.STARPORTREACTOR,
            UnitTypeId.STARPORTTECHLAB,
        ],
        Race.Zerg: [
            UnitTypeId.LARVA,
            UnitTypeId.DRONE,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORDTRANSPORT,
            UnitTypeId.OVERSEER,
            UnitTypeId.QUEEN,
            UnitTypeId.ZERGLING,
            UnitTypeId.BANELING,
            UnitTypeId.ROACH,
            UnitTypeId.RAVAGER,
            UnitTypeId.HYDRALISK,
            UnitTypeId.LURKERMP,
            UnitTypeId.MUTALISK,
            UnitTypeId.CORRUPTOR,
            UnitTypeId.SWARMHOSTMP,
            UnitTypeId.INFESTOR,
            UnitTypeId.VIPER,
            UnitTypeId.ULTRALISK,
            UnitTypeId.BROODLORD,
            UnitTypeId.HATCHERY,
            UnitTypeId.LAIR,
            UnitTypeId.HIVE,
            UnitTypeId.EXTRACTOR,
            UnitTypeId.SPAWNINGPOOL,
            UnitTypeId.ROACHWARREN,
            UnitTypeId.HYDRALISKDEN,
            UnitTypeId.BANELINGNEST,
            UnitTypeId.INFESTATIONPIT,
            UnitTypeId.SPIRE,
            UnitTypeId.GREATERSPIRE,
            UnitTypeId.LURKERDENMP,
            UnitTypeId.ULTRALISKCAVERN,
            UnitTypeId.NYDUSNETWORK,
            UnitTypeId.EVOLUTIONCHAMBER,
            UnitTypeId.SPINECRAWLER,
            UnitTypeId.SPORECRAWLER,
        ],
    }