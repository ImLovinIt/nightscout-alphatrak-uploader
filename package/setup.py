import datetime
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


# Vendor clock corrections.
#
# A meter keeps its own clock and it can be wrong. Readings already synced carry
# whatever it said at the time, so setting the device right fixes future readings
# and repairs none of the history. Correcting the timestamps directly in
# Nightscout does not hold either: the next run re-uploads the vendor's originals,
# and because the upsert keys on created_at the corrected copies sit alongside the
# wrong ones rather than replacing them. The correction therefore belongs here,
# reapplied on every run, so one timestamp per reading is the only thing
# Nightscout ever sees and repeated runs stay idempotent.
#
# Format, one or more rules separated by semicolons:
#
#   at_time_offsets=FROM..TO:+MINUTES
#
# FROM and TO are UTC and are matched against the VENDOR's own uncorrected
# timestamp, never the corrected one, so a rule means the same thing on every run
# regardless of what has already been uploaded. The interval is half open, FROM
# included and TO excluded. MINUTES is signed: a meter running slow, stamping
# readings earlier than they happened, needs a positive value.
#
# Worked example. An AlphaTrak 3 was found 8h08m slow on 2026-08-10. The fault was
# dated to 2026-03-21 by comparing reading times either side of it, the morning
# routine having jumped from 08:24 to 00:00 overnight:
#
#   at_time_offsets=2026-03-21..2026-08-09:+488
#
# Close the window as soon as the device clock is fixed. An open ended correction
# outlives the fault and silently shifts good readings.
def _offset_bound(text, rule):
    try:
        parsed = datetime.datetime.fromisoformat(text.strip())
    except (TypeError, ValueError):
        sys.exit("at_time_offsets: '" + text.strip() + "' is not an ISO date or "
                 "datetime, in rule: " + rule)
    # naive means UTC here, to match the vendor timestamps being compared against
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return round(parsed.timestamp()*1000)


def parse_time_offsets(raw):
    rules = []
    if raw is None or raw.strip() == "":
        return rules
    for rule in raw.split(";"):
        rule = rule.strip()
        if rule == "":
            continue
        if ".." not in rule or ":" not in rule:
            sys.exit("at_time_offsets: expected FROM..TO:+MINUTES, got: " + rule)
        # rpartition, because an ISO datetime contains colons of its own
        window, _, minutes = rule.rpartition(":")
        frm, _, to = window.partition("..")
        try:
            delta = int(minutes.strip())
        except ValueError:
            sys.exit("at_time_offsets: minutes must be a whole number, got '"
                     + minutes.strip() + "' in rule: " + rule)
        start, end = _offset_bound(frm, rule), _offset_bound(to, rule)
        if start >= end:
            sys.exit("at_time_offsets: FROM must be before TO, in rule: " + rule)
        rules.append((start, end, delta*60000))

    # Overlapping windows would make the applied offset depend on rule order,
    # which is not something to leave to chance in a medical record.
    ordered = sorted(rules)
    for earlier, later in zip(ordered, ordered[1:]):
        if later[0] < earlier[1]:
            sys.exit("at_time_offsets: windows overlap, so the offset applied "
                     "would depend on rule order. Fix the ranges.")
    return rules


at_time_offsets = parse_time_offsets(env_str('at_time_offsets'))

retries = env_int('retries', 10)
timeout = env_int('timeout', 10)

if uploader_interval <= 0:
    sys.exit("uploader_interval must be greater than 0.")

# Say it out loud at startup. Rewriting the timestamp on a medical record is not
# something that should ever happen quietly, and this is the one place a reader of
# the logs can see the rule that is in force.
for _start, _end, _delta in sorted(at_time_offsets):
    print("Vendor clock correction active:",
          datetime.datetime.fromtimestamp(_start/1000, datetime.timezone.utc)
          .isoformat(timespec="minutes").replace("+00:00", "Z"),
          "to",
          datetime.datetime.fromtimestamp(_end/1000, datetime.timezone.utc)
          .isoformat(timespec="minutes").replace("+00:00", "Z"),
          "shifted by", str(round(_delta/60000)), "minute(s).",
          "Readings outside that window are untouched.")

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
