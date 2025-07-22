import os
import mysql.connector
from dotenv import load_dotenv


load_dotenv()

db_host = os.environ.get('MYSQL_HOST')
db_user = os.environ.get('MYSQL_USER')
db_name = os.environ.get('MYSQL_DB_NAME')
db_password = os.environ.get('MYSQL_PASSWORD')

if not all([db_host, db_user, db_password, db_name]):
    raise ValueError('Error: Missing required environment variables.')

try:
    print(f"Connecting to MySQL server at {db_host}...")
    database = mysql.connector.connect(
        host=db_host,
        user=db_user,
        password=db_password
    )

    cursor = database.cursor()
    cursor.execute(f'CREATE DATABASE IF NOT EXISTS {db_name}')
    database.commit()
    print(f"Database '{db_name}' created successfully!")
    database.close()

except mysql.connector.Error as err:
    print(f"Error creating database: {err}")
