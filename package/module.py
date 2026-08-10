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
        text = r.data[:300].decode("utf-8", "replace").strip()
        # An expired token is not a 401 and is not JSON. Observed 2026-08-10: a
        # 307 carrying the plain text "The session is no longer valid. Restart
        # the application to continue." Neither the HTTP status nor the JSON
        # StatusCode check below can see that, so match on it here.
        if "session is no longer valid" in text.lower() or r.status in (301, 302, 307, 308, 401, 403):
            print("Zoetis rejected the credentials:", r.status, r.reason, "|", text)
            print("at_token has most likely expired. Capture a fresh one from the app.")
        else:
            print("Zoetis response was not JSON.", r.status, r.reason,
                  "Content Type", r.headers.get('Content-Type'), "|", text)
        return None

    if not isinstance(data, dict):
        print("Zoetis returned", type(data).__name__, "rather than an object.", r.status, r.reason)
        return None

    # The response carries its own success flags and messages beside the HTTP
    # status. Surface them, otherwise a rejection reads as a bare "Data invalid".
    if data.get("StatusCode") != 200 or data.get("IsSuccess") is False:
        print("Zoetis Response Status:", r.status, r.reason,
              "| StatusCode", data.get("StatusCode"), "| IsSuccess", data.get("IsSuccess"))
        for field in ("DisplayMessage", "ExceptionMessage"):
            if data.get(field):
                print("   ", field+":", data[field])
        print("Data invalid. Check your at_token and at_petid.")
        return None

    print("Zoetis Response Status:" , r.status , r.reason)
    return data

# GlucoseEntryDateTime carries no offset. It is UTC. Verified 2026-08-10: the
# newest reading in a capture read 2026-08-08T16:11:00 at 14.1 mmol/L, and the
# app showed that same reading at 02:11 on Sunday 9 August in Sydney, UTC+10.
#
# DateTimeOffset on the request does not affect this. Two captures taken seconds
# apart, one declaring +10:00 and one +00:00, came back byte identical, so the
# response is always in a fixed UTC frame regardless of what the client claims.
#
# The trap worth recording: the readings alone argued the opposite. Seven of the
# newest eight fall at sensible waking hours read as local and only three do read
# as UTC, so the plausible inference was the wrong one. Only the app settled it.
def at_datetime_to_epoch_ms(value):
    try:
        parsed = datetime.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return round(parsed.timestamp()*1000)

# Correct a wrong device clock, per the rule documented in setup.py. Matched on the
# vendor's own uncorrected timestamp, so the same reading always lands on the same
# corrected instant and repeated runs upsert instead of accumulating.
def apply_time_offset(epoch_ms):
    if at_clock_drift is None:
        return epoch_ms
    start, fixed_at, delta = at_clock_drift
    if start <= epoch_ms < fixed_at:
        return epoch_ms + delta
    return epoch_ms

# Not every row in BloodGlucose is a measurement of the animal. Both flags are
# present on every reading of the 2026-08-10 capture and were False throughout,
# so this drops nothing today. A control solution test is a check of the meter
# against a reference fluid, and posting one as a real BG Check would put a
# reading in a medical record that never came from the patient.
def at_reading_is_uploadable(item):
    if item.get("ControlTest") is True:
        return False, "control solution test"
    if item.get("IsDeleted") is True:
        return False, "deleted in the app"
    return True, None

# Nightscout wants "mmol" or "mg/dl" on a treatment, and the response states the
# unit per reading, so read it rather than assume. All 473 readings of the
# 2026-08-10 capture were UnitType "mmol/L", GlucoseUnitId 2. A mg/dL meter would
# otherwise be posted as mmol and read low by a factor of 18.
#
# Only the mmol/L spelling and GlucoseUnitId 2 have been seen. The mg/dL id is
# not guessed at, and the "mg/dl" string below has not been checked against a
# live Nightscout, since no mg/dL account was available to test with.
def at_units(item):
    unit = str(item.get("UnitType") or "").strip().lower()
    if unit in ("mmol/l", "mmol"):
        return "mmol"
    if unit in ("mg/dl", "mgdl"):
        return "mg/dl"
    if item.get("GlucoseUnitId") == 2:
        return "mmol"
    return None

# GlucoseEntryDateTime has minute resolution, and Nightscout upserts a treatment
# on eventType plus created_at, so two readings taken in the same minute collapse
# into one and the earlier is lost with no warning. That is not hypothetical: the
# 2026-08-10 capture held 473 readings on 471 distinct timestamps, losing 13.7 at
# 2026-07-08T14:24 and 17.0 at 2026-01-19T03:48.
#
# Every reading in that capture carried :00 seconds, so the seconds slot is free
# to disambiguate with. Order a collision by PetActivityId, which is unique
# across the response, and push each reading after the first forward one second.
# GDeviceSequenceNumber looks like the natural tiebreaker and is NOT unique, so
# it cannot be used. The result is deterministic, which matters: an arbitrary
# assignment would land on different timestamps each run and accumulate
# duplicates rather than upserting.
def resolve_reading_collisions(parsed): # parsed = a list of (epoch_ms, item)
    by_time = {}
    for epoch, item in parsed:
        by_time.setdefault(epoch, []).append(item)

    resolved = []
    for epoch in sorted(by_time):
        group = by_time[epoch]
        if len(group) == 1:
            resolved.append((epoch, group[0]))
            continue
        # None sorts last rather than raising against an int
        group.sort(key=lambda x: (x.get("PetActivityId") is None, x.get("PetActivityId")))
        if len(group) > 60:
            print("Warning:", len(group), "readings share", to_ns_datestring(epoch),
                  "so the nudge spills into the next minute.")
        for n, item in enumerate(group):
            resolved.append((epoch + n*1000, item))
        print("Nudged", len(group)-1, "reading(s) sharing", to_ns_datestring(epoch),
              "into the seconds slot, so none is lost to the upsert.")
    return resolved

# Process individual BG Check entries.
# Catches per entry so one malformed reading does not discard the whole batch.
def process_at_json_data_prepare_entries(list_data,last_date,list_dict):
    parsed = []
    skipped = {}
    unknown_units = 0
    corrected = 0
    for item in list_data:
        try:
            uploadable, why = at_reading_is_uploadable(item)
            if not uploadable:
                skipped[why] = skipped.get(why, 0)+1
                continue
            entry_date = at_datetime_to_epoch_ms(item.get("GlucoseEntryDateTime"))
            if entry_date is None:
                print("Skipping a reading with an unreadable GlucoseEntryDateTime:",
                      item.get("GlucoseEntryDateTime"))
                skipped["unreadable timestamp"] = skipped.get("unreadable timestamp", 0)+1
                continue
            # Correct the device clock before anything else looks at the time. The
            # collision check below has to run on corrected values, because that is
            # the space Nightscout keys the upsert on, and the date floor has to as
            # well, because Nightscout already holds corrected times.
            shifted = apply_time_offset(entry_date)
            if shifted != entry_date:
                corrected += 1
            parsed.append((shifted, item))
        except Exception as error:
            print("Error reading BloodGlucose entry:", error)

    for why in sorted(skipped):
        print("Skipped", skipped[why], "reading(s):", why)
    if corrected:
        print("Corrected the device clock on", corrected, "of", len(list_data), "reading(s).")

    # Collisions are resolved across every reading, before the date floor is
    # applied, so a reading keeps the same timestamp whatever the floor happens
    # to be on a given run.
    count = 0
    for entry_date, item in resolve_reading_collisions(parsed):
        # Oldest first, so uploader_max_entries takes the oldest unsent readings
        # rather than the newest. Taking the newest would advance the floor past
        # everything older and skip those readings permanently.
        if uploader_max_entries !=0 and count >= uploader_max_entries:
            break
        try:
            if entry_date>last_date or uploader_all_data==True:
                units = at_units(item)
                if units is None:
                    units = "mmol"
                    unknown_units += 1
                entry_dict = {
                    "eventType": "BG Check",
                    "created_at": to_ns_datestring(entry_date),
                    "glucose": item["GlucoseLevel"],
                    "glucoseType": "Finger",
                    "units": units,
                    "enteredBy": ns_uploder,
                }
                list_dict.append(entry_dict)
                count +=1
        except Exception as error:
            print("Error building BloodGlucose entry:", error)

    if unknown_units:
        print("Warning:", unknown_units, "reading(s) state no recognised unit.",
              "Assuming mmol. Check UnitType and GlucoseUnitId in the response.")
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
