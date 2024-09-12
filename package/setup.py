import os
import sys
import datetime
# import docker

# Initilisation for local python script
# at_token = ""
# at_petid = ""
# ns_url = ""
# ns_api_secret= "" # api_secret
# uploader_interval = 30 #mins
# uploader_max_entries = 0 # 0 to disable.
# uploader_all_data = False

# Initilisation for docker & ENV parameters overwrite
try:
    at_token = str(os.environ['at_token'])
except:
    sys.exit("at_token required. Pass it as an Environment Variable.")

try:
    at_petid = int(os.environ['at_petid'])
except:
    sys.exit("at_petid required. Pass it as an Environment Variable.")

try:
    ns_url = str(os.environ['ns_url'])
except:
    sys.exit("ns_url required. Pass it as an Environment Variable.")

try:
    ns_api_secret = str(os.environ['ns_api_secret'])
except:
    sys.exit("ns_api_secret required. Pass it as an Environment Variable.")

try:
    uploader_interval = int(os.environ['uploader_interval'])
except:
    uploader_interval = 30

try:
    uploader_max_entries = int(os.environ['uploader_max_entries'])
except:
    uploader_max_entries = 0

try:
    uploader_all_data = bool(os.environ['uploader_all_data'])
except:
    uploader_all_data = False


#API URL
at_url = "https://alphatrakapi.zoetis.com/api/GetPetActivityByDateWiseList"

# uploader initialisation
ns_uploder = "nightscout-alphatrak-uploader"
ns_unit_convert = 18.018

# header initialisation
ns_header = {"api-secret": ns_api_secret,
             "User-Agent": ns_uploder,
             "Content-Type": "application/json",
             "Accept":"application/json",
             }

at_header = {"Authorization": "Bearer "+at_token,
             "User-Agent": ns_uploder,
             "Content-Type": "application/json",
             "Accept":"application/json",
             }

at_body = {
    "Todate": datetime.datetime.now().isoformat(timespec="seconds"),
    "LanguageId": "7",
    "FromDate": (datetime.datetime.now()-datetime.timedelta(days=365*4)).isoformat(timespec="seconds"),
    "PetId": at_petid,
}

