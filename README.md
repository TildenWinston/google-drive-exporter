# google-drive-exporter
Python script to export files from Google Drive

# Examples of use:

    export.py
      (export all files in their default formats)

    export.py --type spreadsheet
      (export all spreadsheets in the default format)

    export.py --type spreadsheet --export-formats spreadsheet:csv
      (export all spreadsheets in the csv format)

    export.py --export-formats spreadsheet:pdf,document:rtf
      (export all files with their default export formats except
       spreadsheets to be exported to pdf and documents to be
       exported to rtf)

    export.py --destination-dir /tmp/google-files
      (export all files in their default formats but put them in the
       directory /tmp/google-files)

This script uses service account credentials to access your Google Docs
and download them.

# CAVEATS

1. The script can only download documents that the service account has
permission to download.

# How to create a service account

1. Go to the [Google Developer's
Console](https://console.developers.google.com/).

1. Log in with your usual Google credentials.

1. Click on the "Credentials" link.

1. Click on the "Create Credentials" pull-down and choose "Service account
key".

1. On the "Service account" pull-down choose "New service account".

1. For "Key type" choose JSON.

1. Click the "Create" button.

1. Be sure to save the JSON secret file. This is what you will use to
access your files. The script looks for this secret in the file
`client_secret.json`.

1. To download a Google Drive file your must grant view permission on that file
to this e-mail address.

External Libraries required:
* mariadb
* oauth2client
* google-api-python-client
* google-auth-oauthlib

they can be installed by using:
`pip install google-api-python-client oauth2client mariadb google-auth`

Database notes:
user should have the appropiate permissions for creating and editing the speciifed database.
https://stackoverflow.com/questions/8838777/error-1044-42000-access-denied-for-user-localhost-to-database-db

Usage:
One possible usage for the script is to create a takeout of all of your account data and then use this script to download it all. Simply share the takeoutfiles with the service account created earlier. 

To check that downloads were successful take the hash of the files and compare it to the hashes given by the google drive API.
`md5deep -e -w * | tee hashes.txt`
Then take those hashes and compare them to the list of hashses obtained from the API

Next, in this use case, unzipping the files comes next. This bash script unzips the takeout files and puts them in a sub directory.

    #!/bin/sh
    for zip in *.zip
    do
      dirname=$(echo "$zip" | sed 's/\.zip$//')
      echo $dirname
      if mkdir ".//unzipped//${dirname}"
      then
        if cd ".//unzipped//${dirname}"
        then
          unzip "..//..//${zip}" -q
          cd ../..
          rm -f $zip # Uncomment to delete the original zip file
        else
          echo "Could not unpack $zip - cd failed"
        fi
      else
        echo "Could not unpack $zip - mkdir failed"
      fi
    done




