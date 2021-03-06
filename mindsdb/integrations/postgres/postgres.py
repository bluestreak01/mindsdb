import pg8000

from mindsdb_native.libs.constants.mindsdb import DATA_SUBTYPES
from mindsdb.integrations.base import Integration


class PostgreSQL(Integration):
    def __init__(self, config, name):
        self.config = config
        self.name = name

    def _to_postgres_table(self, stats, predicted_cols):
        subtype_map = {
            DATA_SUBTYPES.INT: ' int8',
            DATA_SUBTYPES.FLOAT: 'float8',
            DATA_SUBTYPES.BINARY: 'bool',
            DATA_SUBTYPES.DATE: 'date',
            DATA_SUBTYPES.TIMESTAMP: 'timestamp',
            DATA_SUBTYPES.SINGLE: 'text',
            DATA_SUBTYPES.MULTIPLE: 'text',
            DATA_SUBTYPES.IMAGE: 'text',
            DATA_SUBTYPES.VIDEO: 'text',
            DATA_SUBTYPES.AUDIO: 'text',
            DATA_SUBTYPES.SHORT: 'text',
            DATA_SUBTYPES.RICH: 'text',
            DATA_SUBTYPES.ARRAY: 'text'
        }

        column_declaration = []
        for name, column in stats.items():
            try:
                col_subtype = stats[name]['typing']['data_subtype']
                new_type = subtype_map[col_subtype]
                column_declaration.append(f' "{name}" {new_type} ')
                if name in predicted_cols:
                    column_declaration.append(f' "{name}_original" {new_type} ')
            except Exception:
                print(f'Error: cant convert type {col_subtype} of column {name} to Postgres type')

        return column_declaration

    def _escape_table_name(self, name):
        return '"' + name.replace('"', '""') + '"'

    def _query(self, query):
        con = pg8000.connect(
            database=self.config['integrations'][self.name].get('database', 'postgres'),
            user=self.config['integrations'][self.name]['user'],
            password=self.config['integrations'][self.name]['password'],
            host=self.config['integrations'][self.name]['host'],
            port=self.config['integrations'][self.name]['port']
        )

        cur = con.cursor()
        res = True
        cur.execute(query)

        try:
            rows = cur.fetchall()
            keys = [k[0].decode('ascii') for k in cur.description]
            res = [dict(zip(keys, row)) for row in rows]
        except Exception:
            pass

        con.commit()
        con.close()

        return res

    def setup(self):
        user = f"{self.config['api']['mysql']['user']}_{self.name}"
        password = self.config['api']['mysql']['password']
        host = self.config['api']['mysql']['host']
        port = self.config['api']['mysql']['port']

        try:
            self._query('''
                DO $$
                begin
                    if not exists (SELECT 1 FROM pg_extension where extname = 'mysql_fdw') then
                        CREATE EXTENSION mysql_fdw;
                    end if;
                END
                $$;
            ''')
        except Exception:
            print('Error: cant find or activate mysql_fdw extension for PostgreSQL.')

        self._query('DROP SCHEMA IF EXISTS mindsdb CASCADE')

        self._query(f"DROP USER MAPPING IF EXISTS FOR {self.config['integrations'][self.name]['user']} SERVER mindsdb_server")

        self._query('DROP SERVER IF EXISTS mindsdb_server')

        self._query(f'''
            CREATE SERVER mindsdb_server
                FOREIGN DATA WRAPPER mysql_fdw
                OPTIONS (host '{host}', port '{port}');
        ''')

        self._query(f'''
           CREATE USER MAPPING FOR {self.config['integrations'][self.name]['user']}
                SERVER mindsdb_server
                OPTIONS (username '{user}', password '{password}');
        ''')

        self._query('CREATE SCHEMA mindsdb')

        q = """
            CREATE FOREIGN TABLE IF NOT EXISTS mindsdb.predictors (
                name text,
                status text,
                accuracy text,
                predict text,
                select_data_query text,
                external_datasource text,
                training_options text
            )
            SERVER mindsdb_server
            OPTIONS (dbname 'mindsdb', table_name 'predictors');
        """
        self._query(q)

        q = """
            CREATE FOREIGN TABLE IF NOT EXISTS mindsdb.commands (
                command text
            ) SERVER mindsdb_server
            OPTIONS (dbname 'mindsdb', table_name 'commands');
        """
        self._query(q)

    def register_predictors(self, model_data_arr):
        for model_meta in model_data_arr:
            name = model_meta['name']
            stats = model_meta['data_analysis']
            columns_sql = ','.join(self._to_postgres_table(stats, model_meta['predict']))
            columns_sql += ',"select_data_query" text'
            columns_sql += ',"external_datasource" text'
            for col in model_meta['predict']:
                columns_sql += f',"{col}_confidence" float8'
                if model_meta['data_analysis'][col]['typing']['data_type'] == 'Numeric':
                    columns_sql += f',"{col}_min" float8'
                    columns_sql += f',"{col}_max" float8'
                columns_sql += f',"{col}_explain" text'

            q = f"""
                    CREATE FOREIGN TABLE mindsdb.{self._escape_table_name(name)}
                    (
                        {columns_sql}
                    ) SERVER mindsdb_server
                    OPTIONS (dbname 'mindsdb', table_name '{name}');
            """
            self._query(q)

    def unregister_predictor(self, name):
        q = f"""
            DROP FOREIGN TABLE IF EXISTS mindsdb.{self._escape_table_name(name)};
        """
        self._query(q)

    def check_connection(self):
        try:
            con = pg8000.connect(
                database=self.config['integrations'][self.name].get('database', 'postgres'),
                user=self.config['integrations'][self.name]['user'],
                password=self.config['integrations'][self.name]['password'],
                host=self.config['integrations'][self.name]['host'],
                port=self.config['integrations'][self.name]['port']
            )
            con.run('select 1;')
            con.close()
            connected = True
        except Exception:
            connected = False
        return connected
