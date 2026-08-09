from setup import *
import urllib3
import urllib.parse
import json
import datetime

def convert_mmoll_to_mgdl(x):
    return round(x*ns_unit_convert)

def convert_mgdl_to_mmoll(x):
    return round(x/ns_unit_convert, 1)

# utcfromtimestamp is deprecated from Python 3.12, so build an aware UTC
# datetime instead. Nightscout wants a "Z" suffix rather than "+00:00".
def to_utc_datetime(epoch_ms):
    return datetime.datetime.fromtimestamp(epoch_ms/1000, datetime.timezone.utc)

def to_ns_datestring(epoch_ms):
    return to_utc_datetime(epoch_ms).isoformat(timespec='milliseconds').replace("+00:00", "Z")

# Nightscout rewrites created_at to its own ISO string when it stores a treatment,
# so read it back through a parser rather than string comparing what we posted.
# Returns an epoch in milliseconds, or None if the value could not be read.
def from_ns_datestring(value):
    try:
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return round(parsed.timestamp()*1000)

# NS api v1
# get the most recent treatment of one eventType posted by this uploader.
# Nightscout sorts treatments by created_at descending by default, so count=1
# returns the latest. Returns the treatment dict, or None if there is not one.
def get_last_treatment(header,event_type):
    # Nightscout constrains any query carrying no date clause to the last four days
    # (lib/server/query.js, deltaAgo = TWO_DAYS * 2). A BG Check can easily be older
    # than that when readings are sparse, and without this the lookup returns nothing
    # and every reading is re-posted on every run.
    query = urllib.parse.urlencode({"count": 1,
                                    "find[eventType]": event_type,
                                    "find[enteredBy]": ns_uploder,
                                    "find[created_at][$gte]": "1970",
                                    })
    url = ns_url+"api/v1/treatments.json?"+query
    r = urllib3.request("GET", url=url,headers=header, retries=retries, timeout=timeout)
    try:
        data = json.loads(r.data)
    except json.JSONDecodeError:
        print("Nightscout response was not JSON.", r.status, r.reason,
              "Content Type", r.headers.get('Content-Type'))
        return None

    print("Nightscout get last", event_type+":", r.status , r.reason)
    if not isinstance(data, list) or data == []:
        print("Last", event_type+": no data")
        return None
    else:
        print("Last", event_type+":", data[0].get("created_at"))
        return data[0]

# The upload floor. Returns an epoch in milliseconds so it can be compared with a
# parsed reading time rather than by string, and 0 when Nightscout holds nothing
# yet, which uploads the whole history on a first run.
def get_last_treatment_bgcheck_date(header):
    last = get_last_treatment(header,"BG Check")
    if last is None:
        return 0
    last_date = from_ns_datestring(last.get("created_at"))
    if last_date is None:
        print("Last BG Check has an unreadable created_at. Treating it as 0.")
        return 0
    return last_date

# Nightscout upserts a treatment on eventType plus created_at when no identifier is
# sent, so re-posting the same event overwrites it rather than duplicating it. A
# record stored at the wrong time is never corrected by a later post though, it has
# to be edited by hand, so the timestamps above are worth getting right.
def upload_treatment(treatments_json,header,n): #treatments type = a list of dicts
    url = ns_url+"api/v1/treatments"
    r = urllib3.request("POST", url=url,headers=header, json = treatments_json, retries=retries, timeout=timeout)
    if r.status == 200:
        print("Nightscout POST treatments:", r.status , r.reason)
        print(n, "entry(ies) uploaded.")
    else:
        print("POST Failed.", r.status, r.reason, r.data[:500])

# ======================================================
# get Alphatrak data
# Built to match a capture of the app's own request, field for field and in the
# same order.
#
# The API works in naive local wall clock plus a separately declared offset, so
# the frame has to come from DateTimeOffset rather than from the timestamps.
# astimezone() binds the host's own offset, which keeps the two in step: a
# container left on UTC declares +00:00 and sends UTC wall clocks, one given a TZ
# declares that zone. The previous body sent a naive now() and no offset at all,
# leaving the server to guess. The wall clock values themselves are unchanged by
# this, only the declaration is new.
#
# isoformat would append the offset to Todate and FromDate, which the app does
# not do, so these are formatted by hand.
def return_at_body():
    now = datetime.datetime.now().astimezone()
    # "+1000" -> "+10:00", and half hour zones such as +0930 come out right too
    utc_offset = now.strftime("%z")
    utc_offset = utc_offset[:3]+":"+utc_offset[3:]

    at_body = {
        "PetId": at_petid,
        # Empty asks for the whole window. This is the app's delta sync handle,
        # and the uploader filters client side against Nightscout instead, so
        # there is nothing to put here yet.
        "LastcallAPItime": "",
        # The app sends "1". Where "7" came from is not recorded, and no capture
        # shows it. It most likely only selects the language of any text in the
        # response, but match the app rather than guess.
        "LanguageId": "1",
        # Note the space separator and the space before the offset. The two
        # fields below use "T" instead. That inconsistency is the app's.
        "DateTimeOffset": now.strftime("%Y-%m-%d %H:%M:%S ")+utc_offset,
        "Todate": now.strftime("%Y-%m-%dT%H:%M:%S"),
        # Two years, the window the app itself asks for. A timedelta rather than
        # replace(year=year-2) so a run on 29 February does not raise.
        "FromDate": (now-datetime.timedelta(days=365*2)).strftime("%Y-%m-%dT%H:%M:%S"),
    }
    # print("Alphatrak query todate:",at_body["Todate"])
    return at_body


# Returns the parsed response, or None if it was unusable. Returning None keeps
# the scheduler alive so a bad response only costs one run.
def get_at_entries(header,body):
    url = at_url
    r = urllib3.request("POST", url=url,headers=header, body=json.dumps(body), retries=retries, timeout=timeout)
    try:
        data = json.loads(r.data)
    except json.JSONDecodeError:
        print("Zoetis response was not JSON.", r.status, r.reason,
              "Content Type", r.headers.get('Content-Type'))
        return None

    print("Zoetis Response Status:" , r.status , r.reason)
    if data.get("StatusCode") != 200:
        print("Data invalid. Check your at_token and at_petid.")
        return None
    return data

# GlucoseEntryDateTime carries no offset, so something has to decide what it means.
# Reading it as UTC is what the code has always done, by appending "Z" to it, and
# that is kept here so this change moves no data. It has not been checked against
# a reading whose true wall clock time is known, and the vendor timestamp lesson
# from the sibling uploader says do not assume: verify before trusting it.
def at_datetime_to_epoch_ms(value):
    try:
        parsed = datetime.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return round(parsed.timestamp()*1000)

# Process individual BG Check entries.
# Catches per entry so one malformed reading does not discard the whole batch.
def process_at_json_data_prepare_entries(list_data,last_date,list_dict):
    count = 0
    for item in list_data:
        if uploader_max_entries !=0 and count >= uploader_max_entries:
            break
        try:
            entry_date = at_datetime_to_epoch_ms(item["GlucoseEntryDateTime"])
            if entry_date is None:
                print("Skipping a reading with an unreadable GlucoseEntryDateTime:",
                      item.get("GlucoseEntryDateTime"))
                continue
            if entry_date>last_date or uploader_all_data==True:
                entry_dict = {
                    "eventType": "BG Check",
                    "created_at": to_ns_datestring(entry_date),
                    "glucose": item["GlucoseLevel"],
                    "glucoseType": "Finger",
                    "units": "mmol",
                    "enteredBy": ns_uploder,
                }
                list_dict.append(entry_dict)
                count +=1
        except Exception as error:
            print("Error reading BloodGlucose entry:", error)
    return list_dict


# A single reading comes back as a bare dict rather than a one item list, so both
# shapes have to be accepted.
def process_at_json_data(data,last_date):
    list_dict = []
    print("Processing data...")
    try:
        readings = data["ResponseData"]["PetActivity"]["BloodGlucose"]
        if isinstance(readings, dict):
            readings = [readings]
        if not isinstance(readings, list):
            print(type(readings), " recieved. Check API content.")
            readings = []
        if len(readings) > 0:
            process_at_json_data_prepare_entries(readings,last_date,list_dict)
        else:
            print("Blood glucose list empty. Take a reading to start.")
    except Exception as error:
        print("Error reading BloodGlucose:", error)

    if len(list_dict) > 0:
        print("Uploading", len(list_dict), "entry(ies)...")
        upload_treatment(list_dict,ns_header,len(list_dict))
    else:
        print("No new entry found.")
