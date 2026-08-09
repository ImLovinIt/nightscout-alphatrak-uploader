import os
import sys

# Initilisation for local python script
# at_token = ""
# at_petid = 0
# ns_url = ""
# ns_api_secret= "" #api_secret
# uploader_interval = 30 #mins
# uploader_max_entries = 0 # 0 to disable.
# uploader_all_data = False
# retries = 10
# timeout = 10

# Environment variable readers.
# A bare "except" here would also swallow KeyboardInterrupt and SystemExit, and
# str/int/bool each need different handling, so read them explicitly instead.
def env_str(name, default=None, required=False):
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        if required:
            sys.exit(name + " required. Pass it as an Environment Variable.")
        return default
    return value


def env_int(name, default=None, required=False):
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        if required:
            sys.exit(name + " required. Pass it as an Environment Variable.")
        return default
    try:
        return int(value)
    except ValueError:
        sys.exit(name + " must be a whole number. Got: " + value)


def env_bool(name, default=False):
    # bool("False") is True, so the string has to be compared, not cast.
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("true", "1", "yes", "on")


# Initilisation for docker & ENV parameters overwrite
at_token = env_str('at_token', required=True)
at_petid = env_int('at_petid', required=True)
ns_url = env_str('ns_url', required=True)
ns_api_secret = env_str('ns_api_secret', required=True)

# Every Nightscout call concatenates a path straight onto ns_url, so a missing
# trailing slash turns https://host + api/v1/treatments into https://hostapi/v1/treatments
# and the whole run fails on DNS. Guarantee the separator here instead of trusting
# the variable, and strip stray whitespace while at it.
ns_url = ns_url.strip().rstrip("/")+"/"

# urllib3 cannot request a schemeless URL, and the failure it raises is not obvious,
# so say so plainly at startup. at_url is a constant below and needs no check.
if not ns_url.lower().startswith(("http://", "https://")):
    sys.exit("ns_url must start with http:// or https://. Got: " + ns_url)

uploader_interval = env_int('uploader_interval', 30)
uploader_max_entries = env_int('uploader_max_entries', 0)
uploader_all_data = env_bool('uploader_all_data', False)

retries = env_int('retries', 10)
timeout = env_int('timeout', 10)

if uploader_interval <= 0:
    sys.exit("uploader_interval must be greater than 0.")

#API URL
at_url = "https://alphatrakapi.zoetis.com/api/GetPetActivityByDateWiseList"

# uploader initialisation
# This string is written to enteredBy on every treatment and is matched on when
# reading the last one back, so changing it orphans everything already posted.
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
