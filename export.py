#!/usr/bin/python
# Adapted from https://developers.google.com/drive/v3/web/quickstart/python

from __future__ import print_function
import io
import mimetypes
from winreg import REG_RESOURCE_REQUIREMENTS_LIST
import httplib2
import sys
import os
import re
import pprint
import copy
import argparse
import mariadb
import threading

from apiclient import discovery
import oauth2client
from oauth2client import client
from oauth2client import tools
from oauth2client.service_account import ServiceAccountCredentials
from httplib2 import Http
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from getfilelistpy import getfilelist # gets google drive folder structures

pp = pprint.PrettyPrinter(indent=4)

DEBUG = False
QUIET = False

SCOPES             = 'https://www.googleapis.com/auth/drive.readonly'
CLIENT_SECRET_FILE = 'client_secret.json'
APPLICATION_NAME   = 'Drive API Python Exporter'
DESTINATION_DIR    = '/media/sf_google_docs_backup'
AUTH_METHOD        = ''
#DESTINATION_DIR    = '/media/sf_TEMP'
#DB Caching related settings
DB_ENABLED         = True
DB_USER            = "pythonUser"
DB_PASSWORD        = ""
DB_HOST            = "127.0.0.1"
DB_PORT            = 3306
DB_DATABASE        = "employees"
DB_THRESHHOLD      = 10000
DB_TABLE           = "downloadStatus"

#multithreading
MULTITHREADED    = True
MULTITHREADED_MAX_THREADS = 100




# A convenience hash to map from short document type to official
# Google mime-type. See also
# https://developers.google.com/drive/v3/web/mime-types
TYPE_TO_GOOGLE_MIME_TYPE = {
    'audio':        'application/vnd.google-apps.audio',
    'document':     'application/vnd.google-apps.document',
    'drawing':      'application/vnd.google-apps.drawing',
    'file':         'application/vnd.google-apps.file',
    'folder':       'application/vnd.google-apps.folder',
    'form':         'application/vnd.google-apps.form',
    'fusiontable':  'application/vnd.google-apps.fusiontable',
    'map':          'application/vnd.google-apps.map',
    'photo':        'application/vnd.google-apps.photo',
    'presentation': 'application/vnd.google-apps.presentation',
    'script':       'application/vnd.google-apps.script',
    'sites':        'application/vnd.google-apps.sites',
    'spreadsheet':  'application/vnd.google-apps.spreadsheet',
    'unknown':      'application/vnd.google-apps.unknown',
    'video':        'application/vnd.google-apps.video',
}

# Reverse the TYPE_TO_GOOGLE_MIME_TYPE mapping.
GOOGLE_MIME_TYPE_TO_TYPE = dict((v, k) for k, v in TYPE_TO_GOOGLE_MIME_TYPE.items())

# Mapping from document type to MIME type. See also
# https://developers.google.com/drive/v3/web/manage-downloads
DOCUMENT_TYPE_TO_MIME_TYPE = {
    'html':        'text/html',
    'text':        'text/plain',
    'rtf':         'application/rtf',
    'open-office': 'application/vnd.oasis.opendocument.text',
    'pdf':         'application/pdf',
    'ms-word':     'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}
SPREADSHEET_TYPE_TO_MIME_TYPE = {
    'ms-excel':    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'open-office': 'application/x-vnd.oasis.opendocument.spreadsheet',
    'pdf':         'application/pdf',
    'csv':         'text/csv',
}
DRAWING_TYPE_TO_MIME_TYPE = {
    'jpeg': 'image/jpeg',
    'png':  'image/png',
    'svg':  'image/svg+xml',
    'pdf':  'application/pdf',
}
PRESENTATION_TYPE_TO_MIME_TYPE = {
    'ms-powerpoint': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'pdf':           'application/pdf',
    'text':          'text/plain',
}
SCRIPT_TYPE_TO_MIME_TYPE = {
    'json': 'application/vnd.google-apps.script+json',
}

TYPE_TO_EXPORTS = {
    'spreadsheet':   SPREADSHEET_TYPE_TO_MIME_TYPE,
    'document':      DOCUMENT_TYPE_TO_MIME_TYPE,
    'drawing':       DRAWING_TYPE_TO_MIME_TYPE,
    'presentation':  PRESENTATION_TYPE_TO_MIME_TYPE,
    'script':        SCRIPT_TYPE_TO_MIME_TYPE,
}

TYPE_DEFAULT_EXPORT_TYPE = {
    'spreadsheet':  'ms-excel',
    'document':     'ms-word',
    'drawing':      'png',
    'presentation': 'ms-powerpoint',
    'script':       'json',
}

def export_type_help(type):
    type_to_mimetype = TYPE_TO_EXPORTS[type]
    default_export_type = TYPE_DEFAULT_EXPORT_TYPE[type]

    rv = ''

    rv = '  * ' + type + '\n'
    for export_type in sorted(type_to_mimetype.keys()):
        mimetype = type_to_mimetype[export_type]
        if (export_type == default_export_type):
            default_string = ' [DEFAULT]'
        else:
            default_string = ''
        rv += '    + {0}:{1}{2}'.format(type, export_type, default_string) + "\n"

    return rv

def db_connect():
    try:
        conn = mariadb.connect(
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT,
            autocommit=False
        )
        return conn

    except mariadb.Error as e:
        print(f"Error connecting to MariaDB Platform: {e}")
        return False

    except Exception as e:
        print(f"Some error occured: {e}")
        return False

# Create a file with the given contents
def spew(contents, filename):
    full_path = os.path.join(DESTINATION_DIR, filename)
    with open(full_path,'wb') as f:
        f.write(contents)
    return full_path

def get_credentials():
    """Gets valid user credentials from storage.

    Returns:
    Credentials, the obtained credential.
    """

    debug_progress('getting secret from secret file and creating credentials object')
    scopes      = [SCOPES]
    credentials = ServiceAccountCredentials.from_json_keyfile_name(CLIENT_SECRET_FILE, scopes=''.join(scopes))
    http_auth   = credentials.authorize(Http())

    return http_auth

def db_setup(database, table):
    conn = False
    if DB_ENABLED:
        conn = db_connect()
        if conn != False:
            cur = conn.cursor()

            try:
                # Not the safest way to build a query, but for local use, this should be acceptable
                # Create the database if it doesn't exist
                query = f'CREATE DATABASE IF NOT EXISTS `{database}`'
                cur.execute(query)

                # Selects the database
                query = f'USE `{database}`'
                cur.execute(query)
                
                # Creates the table if it doesn't exist
                query = f"""CREATE TABLE IF NOT EXISTS `{table}` (
	            `id` VARCHAR(50) NOT NULL COLLATE 'latin1_swedish_ci',
	            `name` VARCHAR(260) NULL DEFAULT NULL COLLATE 'latin1_swedish_ci',
	            `mimeType` VARCHAR(100) NULL DEFAULT NULL COLLATE 'latin1_swedish_ci',
	            `size` BIGINT(20) NULL DEFAULT NULL,
                `md5Checksum` VARCHAR(33) NULL DEFAULT NULL,
                `sha256Checksum` VARCHAR(64) NULL DEFAULT NULL,
                `status` VARCHAR(50) NULL DEFAULT NULL
                )
                COLLATE='latin1_swedish_ci'
                ENGINE=InnoDB
                ;"""
                cur.execute(query)

                conn.commit()

            except Exception as e:
                print(f"Error: {e}")
    
    return conn

def authToGoogle():
    if AUTH_METHOD == "serviceaccount":
        http_auth = get_credentials()
        service   = discovery.build('drive', 'v3', http=http_auth)
        debug_progress('created Google Drive service object')
    
    elif AUTH_METHOD == "oauth":
        """Shows basic usage of the Drive v3 API.
        Prints the names and ids of the first 10 files the user has access to.
        """
        creds = None
        # The file token.json stores the user's access and refresh tokens, and is
        # created automatically when the authorization flow completes for the first
        # time.
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        # If there are no (valid) credentials available, let the user log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open('token.json', 'w') as token:
                token.write(creds.to_json())

        try:
            service = build('drive', 'v3', credentials=creds)

        except HttpError as error:
            # TODO(developer) - Handle errors from drive API.
            exit_with_error('An error occured: \'{0}\''.format(error))

    else:
        exit_with_error("Error: please select a supported auth method.'serviceaccount' or 'oauth' are currently supported. {AUTH_METHOD} is not supported.")

    return service

def debug_progress(msg):
    if (DEBUG):
        print('debug_progress: ' + msg)

def progress(msg):
    if (not QUIET):
        print(msg)

# Normalize a filename (replace spaces with underscores, etc.)
def normalize_filename(name):
    # Squish multiple spaces to a single space
    normalized = re.sub(r"\s+", ' ', name)

    # Replace spaces with underscores
    # normalized =  re.sub(r"\s", '_', normalized)

    return normalized

def escape_quotes(name):
    # Squish multiple spaces to a single space
    normalized = re.sub(r"'", '\\\'', name)

    # Replace ' with \'

    return normalized

# Create a mapping from the type to the default export type based starting
# from TYPE_DEFAULT_EXPORT_TYPE
def build_type_to_export_format(export_format):
   # Make a copy of the built-in default export type mapping
   type_to_export_format = copy.copy(TYPE_DEFAULT_EXPORT_TYPE)

   if (not export_format):
       # nothing passed in export_format, so we use all the deftauls.
       return type_to_export_format

   # If we get here, we have some export formats to override.
   export_formats = export_format.split(',')

   # Now override the mappings in type_to_export_format with the passed-in
   # export_format parameter.
   for export_format in export_formats:
       # export_format should have the format <type>:<format>
       type_and_format = export_format.split(':')
       if (len(type_and_format) != 2):
           msg = 'could not parse export format \'{0}\''.format(export_format)
           exit_with_error(msg)
       else:
           type   = type_and_format[0]
           format = type_and_format[1]
           if (not(type in TYPE_TO_EXPORTS)):
               msg = 'the type \'{0}\' does not have export formats'.format(type)
               exit_with_error(msg)
           else:
               if (not (format in TYPE_TO_EXPORTS[type])):
                   msg = 'type \'{0}\' does not export to format \'{1}\''.format(type, format)
                   exit_with_error(msg)
               else:
                   type_to_export_format[type] = format

   return type_to_export_format

def build_google_types_to_export(types_to_export):
    google_types_to_export = []
    for type in types_to_export:
        google_types_to_export.append(TYPE_TO_GOOGLE_MIME_TYPE[type])
        export_all = False

    return google_types_to_export


def process_current(service, results, types_to_export, export_formats, destination_dir, conn):
    export_all = True
    usedb = False
    cur = None

    if conn != False:
        cur = conn.cursor()

    # Convert types into an array of google types.
    google_types_to_export = []

    for type in types_to_export:
        google_types_to_export.append(TYPE_TO_GOOGLE_MIME_TYPE[type])
        export_all = False

    type_to_export_format = build_type_to_export_format(export_formats)

    items = results.get('files', [])

    for item in items:
        name            = item['name']
        id              = item['id']
        google_mimetype = item['mimeType']
        

        # We never export folders.
        if (google_mimetype == 'application/vnd.google-apps.folder'):
            debug_progress('skipping folder \'{0}\''.format(name))
            continue

        # Moving because folders do not have these fields
        size            = item['size']
        # [TODO] Doesn't apply to google docs or sheets, etc so handling needs to be added
        # md5Hash         = item['md5Checksum']

        # Check Database
        completed = False

        if cur is not None and (int(size) > DB_THRESHHOLD):
            query = f'SELECT name,id,mimeType,size,md5Checksum,status FROM {DB_TABLE} WHERE id=\'{id}\''
            cur.execute(query)
            if cur.rowcount >= 1:
                for result in cur:
                    if (result[1] == id) and result[5]: #and result[4] == md5Hash:
                        completed = True
                        break

            if completed:
                continue        

        # Checks either all files should be exported or that
        # the item is of a specified type
        if (export_all or (google_mimetype in google_types_to_export)):
            # Get the type from the Google mimetype
            if (google_mimetype in GOOGLE_MIME_TYPE_TO_TYPE):
                type = GOOGLE_MIME_TYPE_TO_TYPE[google_mimetype]
            else:
                # Unrecognized type, but that's OK as it just means it's
                # not one we just download as-is.
                type = None

            debug_progress('found file to export of type \'{0}\''.format(type))

            # Set export type (if this one of the types that can have the
            # export format set) for Google formats
            if (type and (type in type_to_export_format)):
                export_format   = type_to_export_format[type]
                export_mimetype = TYPE_TO_EXPORTS[type][export_format]
            else:
                export_mimetype = None

            debug_progress('export_mimetype is \'{0}\''.format(export_mimetype))
            debug_progress('exporting \'{0}\'({1}): mimetype: {2}'.format(name, id, google_mimetype))

            normalized_filename = normalize_filename(name)
            full_destination_path = os.path.join(destination_dir, normalized_filename)
            debug_progress('destination file full path is \'{0}\''.format(full_destination_path))

            if (export_mimetype):
                results_of_export = service.files().export(fileId=id, mimeType=export_mimetype).execute()
                full_path = spew(results_of_export, full_destination_path)
            else:
                try:
                    request = service.files().get_media(fileId=id)
                    file = io.FileIO(full_destination_path, 'wb')
                    # [TODO] Should set chunk size dynaically. Value is in bytes, 1 Gibibyte currently set
                    downloader = MediaIoBaseDownload(file, request, 1024*1024*1024)
                    done = False
                    while done is False:
                        status, done = downloader.next_chunk()
                        print(F'Download {int(status.progress() * 100)}.')

                    try:
                        md5Hash     = item['md5Checksum']
                        sha256Hash  = item['sha256Checksum']

                    except Exception as e:
                        md5Hash     = "NA"
                        sha256Hash  = "NA"
                
                except HttpError as error:
                    print(F'An error occurred: {error}')
                    file = None



            # full_path = spew(results_of_export, full_destination_path)
            debug_progress('exported to file {0}'.format(full_destination_path))
            # progress('exported file \'{0}\' to file \'{1}\' [{2}]'.format(name, full_path, export_mimetype))

            #Add success to DB
            if cur is not None and int(size) > DB_THRESHHOLD:
                query = f'INSERT INTO {DB_TABLE} (name,id,mimeType,size,md5Checksum,status) VALUES (\'{name}\', \'{id}\', \'{google_mimetype}\', {size}, \'{md5Hash}\', True)'
                cur.execute(query)
    
    if cur is not None:
        conn.commit()


def parse_arguments():
    google_types = TYPE_TO_GOOGLE_MIME_TYPE.keys()

    parser = argparse.ArgumentParser()

    # --debug flag
    parser.add_argument("--debug",
                        help="show details of what is happening",
                        action="store_true")
    # --type
    help_text_type = """The type(s) of Google document to export.
    For more details, use the --help-extended option."""
    parser.add_argument("--type",
                        help=help_text_type,
                        )
    # --export-format
    help_text_export = """The format of document that will be saved.
    For more details, use the --help-extended option."""
    parser.add_argument("--export-formats",
                        help=help_text_export,
                        )
    # --destination-dir
    help_text_destination_dir = """The directory where all the exported files will
    be put. If omitted the current directory will be used. If the
    directory indicated does not exist, the script will abort."""
    parser.add_argument("--destination-dir",
                        help=help_text_destination_dir,
                        )

    # --auth-method
    help_text_auth_method = """Authentication style to use for the script. 
    The script can either use a service account or can use OAUTH. The 
    two valid options are: 'serviceaccount' or 'oauth' """    
    parser.add_argument("--auth-method",
                        help=help_text_auth_method,
                        )      
    # --help-extended
    help_text_help_extended = """Show more detailed help."""
    parser.add_argument("--help-extended",
                        help=help_text_help_extended,
                        action="store_true"
                        )
    # DB related
    help_text_db_enabled = """True enables DB caching, False disables db caching"""
    parser.add_argument("--db-enabled",
                        help=help_text_db_enabled,
                        )

    help_text_db_user = """Username for the db"""
    parser.add_argument("--db-user",
                        help=help_text_db_user,
                        )

    help_text_db_password = """Password for the db"""
    parser.add_argument("--db-password",
                        help=help_text_db_password,
                        )

    help_text_db_host = """Hostname for the db"""
    parser.add_argument("--db-host",
                        help=help_text_db_host,
                        )
                        
    help_text_db_port = """Port number for the db"""
    parser.add_argument("--db-port",
                        help=help_text_db_port,
                        )

    help_text_db_database = """Database name for the db"""
    parser.add_argument("--db-database",
                        help=help_text_db_database,
                        )

    help_text_db_threshhold = """File size threshhold for entries getting added to 
    the DB or for checking the DB for a file. Strives to balance time spent downloading
     files and time spent querrying the DB"""
    parser.add_argument("--db-threshhold",
                        help=help_text_db_threshhold,
                        )
    # print(help_text_extended)

    # sys.exit(0)
    return parser

def help_extended_text():

    google_types = TYPE_TO_GOOGLE_MIME_TYPE.keys()
    google_types_formatted = '\n'.join(map((lambda x: '  * ' + x), sorted(google_types)))

    doc_export_types = DOCUMENT_TYPE_TO_MIME_TYPE.values()
    doc_export_types_formatted = DOCUMENT_TYPE_TO_MIME_TYPE.values()

    export_help_text_aux = ''
    for type in sorted(TYPE_TO_EXPORTS.keys()):
        export_help_text_aux += export_type_help(type)

    help_text_extended = """
--type
Use the --type option to specify which types of Google documents to
export. If the --type option is not used, the script will export ALL the
documents that the credentials can access. To restrict the types exported,
provide a comma-delimited list of types. The valid types to export are:
{0}
See also https://developers.google.com/drive/v3/web/manage-downloads

--export-formats
Use the --export-formats to specify the format of the downloaded file.
This is only relevant for the spreadsheet, document, presentation,
drawing, and script types. If not specified, will output the defualt
type. You specify the export formats as a comma-delimited set of mappings.
Here are the available export formats:
{1}
Examples:
  export.py
      (export all files in their default formats)

  export.py --type spreadsheet
      (export all spreadsheets in the default format)

  export.py --type spreadsheet,audio,photo
      (export all spreadsheets, audio files, and photos)

  export.py --type spreadsheet --export-formats spreadsheet:csv
      (export all spreadsheets in the csv format)

  export.py --export-formats spreadsheet:pdf,document:rtf
      (export all files with their default export formats except
       spreadsheets to be exported to pdf and documents to be
       exported to rtf)
""".format(google_types_formatted, export_help_text_aux).strip()

    return help_text_extended

def exit_with_error(msg):
    print('error: ' + msg.strip())
    sys.exit(1)

def getFileThread():
    service = authToGoogle()
    pageSize = 10
    nextPageToken = None
    first_pass = True
    filesListed = 0
    conn = db_setup(DB_DATABASE, DB_TABLE)

    while (first_pass or nextPageToken):
        nextPageToken = getFileListAndAddToDB(service, conn, pageSize, nextPageToken)
        
        filesListed += pageSize
        if (filesListed % 1000) == 0:
            progress("Exported: {0} files".format(filesListed))
        
        first_pass = False


def getFileListAndAddToDB(service, conn, pageSize, nextPageToken):
    results = service.files().list(pageSize=pageSize,
                                       pageToken=nextPageToken,
                                       fields="nextPageToken, kind, files(id, name, mimeType, size, md5Checksum, sha256Checksum, webContentLink)").execute()

    if conn is False:
        msg = 'Database not connected. Double check database connection and try again'
        exit_with_error(msg)

    cur = conn.cursor()

    for file in results.get('files', []):
        # add to db

        name            = file['name']
        id              = file['id']
        google_mimetype = file['mimeType']

        # Skip folders
        if (google_mimetype == 'application/vnd.google-apps.folder'):
            debug_progress('skipping folder \'{0}\''.format(name))
            continue

        # Moving because folders do not have these fields
        size            = file['size']
        
        try:
            md5Hash     = file['md5Checksum']
            sha256Hash  = file['sha256Checksum']

        except Exception as e:
            md5Hash     = "NA"
            sha256Hash  = "NA"

        #need to handle ' chars in names
        name = escape_quotes(name)

        if cur is not None:
                query = f'INSERT INTO {DB_TABLE} (name,id,mimeType,size,md5Checksum,sha256Checksum,status) VALUES (\'{name}\', \'{id}\', \'{google_mimetype}\', {size}, \'{md5Hash}\', \'{sha256Hash}\', True)'
                cur.execute(query)

    if cur is not None:
        conn.commit()

    return results.get('nextPageToken')

def new_main():
    max_threads = 12
    # current_threads = 0 threading.activeCount()

    # Get list of files and add them to the database
    tGetFileList1 = threading.Thread(target=getFileThread, args=())
    tGetFileList1.start()
    # Fill in folder structure?
    # tGetFolderStructure = threading.Thread()

    # Start downloading files
    tDownloadFile1 = threading.Thread()


def main():
    parser = parse_arguments()
    args   = parser.parse_args()

    if args.help_extended:
        print(help_extended_text())
        sys.exit(0)

    if args.debug:
        global DEBUG
        DEBUG = True

    # We start with destination_dir pointing to the current directory, and
    # then override if necessary.
    destination_dir = os.getcwd()
    if (args.destination_dir):
        destination_dir = args.destination_dir

    debug_progress('destination directory is \'{0}\''.format(destination_dir))
    if (not os.path.isdir(destination_dir)):
        exit_with_error('destination directory \'{0}\' does not exist'.format(destination_dir))

    # If the --type argument was passed, parse it now to get the types of
    # files we want exported.
    if (args.type):
        types = args.type.split(',')

        # Make sure each type is valid
        for type in types:
            if (not(type in TYPE_TO_GOOGLE_MIME_TYPE)):
                exit_with_error('unrecognized type \'{0}\''.format(type))
    else:
        # This means export ALL types.
        types = []

    # types is an array that now contains those types of documents we want
    # exported, or, if the empty array, means we want to export ALL file
    # types.

    # Database Args reading
    if args.db_enabled:
        global DB_ENABLED
        DB_ENABLED = args.db_enabled
    
    if args.db_user:
        global DB_USER
        DB_USER = args.db_user

    if args.db_password:
        global DB_PASSWORD
        DB_PASSWORD = args.db_password

    if args.db_host:
        global DB_HOST
        DB_HOST = args.db_host

    # TODO Finish Parsing DB Vals

    if args.auth_method:
        global AUTH_METHOD
        AUTH_METHOD = args.auth_method

    service = authToGoogle()

    conn = False
    conn = db_setup(DB_DATABASE, DB_TABLE)

    new_main()

    first_pass = True
    nextPageToken = None
    filesListed = 0
    pageSize = 10
    while (first_pass or nextPageToken):
        results = service.files().list(pageSize=pageSize,
                                       pageToken=nextPageToken,
                                       fields="nextPageToken, kind, files(id, name, mimeType, size, md5Checksum, webContentLink)").execute()
        nextPageToken = results.get('nextPageToken')
        
        filesListed += pageSize
        if (filesListed % 10000) == 0:
            progress("Exported: {0}".format(filesListed))
        
        process_current(service, results, types, args.export_formats, destination_dir, conn)

        first_pass = False

    debug_progress('Finished')

if __name__ == '__main__':
    main()