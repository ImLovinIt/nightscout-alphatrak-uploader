# Nightscout Alphatrak Uploader
Script written in python to periodically upload Zoetis Alphatrak glucose data to Nightscout.

*Only tested with Zoetis Alphatrak 3

Readings are posted as Nightscout `BG Check` treatments, not as CGM entries, because an Alphatrak reading is a meter test taken by hand rather than a continuous trace.

## Configuration
The script takes the following environment variables.

### Required

| Variable        | Description                                   | Example                                  |
|-----------------|-----------------------------------------------|------------------------------------------|
| `at_token`      | Alphatrak bearer token. See below.            | YGza5ertORghredgUOXAQw... (256 characters) |
| `at_petid`      | Alphatrak pet id, a whole number. See below.  | 12345                                    |
| `ns_url`        | Nightscout host, with scheme. Trailing / optional. | https://nightscout.example.com/     |
| `ns_api_secret` | SHA1 hash of a Nightscout access token.       | 162f14de46149447c3338a8286223de407e3b2fa |

### Optional

| Variable               | Description                                        | Default |
|------------------------|----------------------------------------------------|---------|
| `uploader_interval`    | Minutes between polls of Alphatrak.                | `30`    |
| `uploader_max_entries` | Cap on entries per upload. `0` disables the cap.   | `0`     |
| `uploader_all_data`    | Upload every available reading, not just new ones. | `False` |
| `retries`              | Retries per API request.                           | `10`    |
| `timeout`              | Timeout in seconds per retry.                      | `10`    |
| `at_clock_drift_minutes`  | Correct a wrong meter clock. See below.         | unset   |
| `at_clock_drift_from`     | When the clock fault began.                     | unset   |
| `at_clock_drift_fixed_at` | When you corrected the device clock.            | unset   |

### Correcting a wrong meter clock
The meter keeps its own clock, and it can be wrong. Readings already synced carry
whatever it said at the time, so setting the device right fixes future readings
and repairs none of the history.

Correcting the timestamps by hand in Nightscout does not hold either. The next run
re-uploads the vendor's originals, and because Nightscout matches a treatment on
event type plus timestamp, the corrected copies end up sitting beside the wrong
ones instead of replacing them. So the correction is applied here, on every run,
which keeps one timestamp per reading and leaves repeated runs idempotent.

Three variables, all of them or none:

```
at_clock_drift_minutes=488
at_clock_drift_from=2026-03-21
at_clock_drift_fixed_at=2026-08-10T21:00+10:00
```

`at_clock_drift_minutes` is signed. A meter running slow, stamping readings earlier
than they really happened, needs a positive value.

Both dates are matched against the **meter's own uncorrected timestamp**, so the
rule means the same thing on every run no matter what has already been uploaded.
The range includes `from` and excludes `fixed_at`. Naive values are read as UTC, or
paste a local time with its offset as above, which is harder to get wrong.

`fixed_at` is the right boundary, and it is provably the correct one. A reading
taken before the fix is stamped earlier than it happened, so it falls below
`fixed_at` and is corrected. A reading taken afterwards is stamped at its true
time, so it falls at or above `fixed_at` and is left alone. That holds however many
readings fall either side, so you do not have to avoid testing before you get round
to fixing the clock.

### The order matters
**Record the drift before you reset the device clock.** Resetting it destroys the
only evidence of how far out it was, permanently. Photograph the meter screen
beside a phone showing the time.

1. Compare the meter against a phone. This gives you `minutes`.
2. Fix the device clock, and note the moment. This gives you `fixed_at`.
3. Capture the readings and date the onset. This gives you `from`. The vendor never
   changes a stored timestamp, so a capture taken afterwards still shows the fault.
4. Check that the onset boundary implies roughly the drift you measured. If the two
   disagree by more than an hour or so, the clock drifted gradually rather than
   jumping, a flat correction is the wrong tool, and leaving the history alone is
   the safer choice.
5. Set the three variables and restart. Read the startup line and the per run count.
6. Delete the wrongly timed records once. The correction stops new ones being
   written, it cannot remove what is already stored.

**Date the fault, do not guess it.** A clock fault shows up as an abrupt, lasting
shift in a routine that was previously steady. Guessing `from` too early corrupts
readings that were fine, and too late leaves wrong ones in place.

### What is checked for you
The uploader refuses to start if only some of the three are set, if the drift is
zero, if `from` is not before `fixed_at`, or if **`fixed_at` is in the future**.
That last one is the important guard: whoever types a drift has already fixed the
device, so a future value means either the clock is not fixed yet or a local time
was written without its offset and read as UTC, which is the easiest mistake to
make here.

There is deliberately **no switch to turn the correction off**. The vendor keeps
serving the original wrong timestamps forever, so disabling the rule would write
them straight back on the next full upload. The rule stays in your configuration
permanently. What is bounded is the window, not the rule's life.

The uploader prints the rule in force at startup and reports how many readings it
shifted on each run, because rewriting a timestamp on a medical record should
never happen quietly.

**The uploader cannot detect a clock fault, and will not warn you about one.** It
only applies corrections you have configured by hand. The fault above ran for
nearly five months before anyone noticed, and nothing in the data reliably reveals
one: the vendor's own sync timestamp looks like a clue, but it is dominated by how
long a reading sat unsynced, which can be months, so it raises far more false
alarms than real ones.

Check the meter's clock against a phone every so often. It is on the device screen
and the comparison takes seconds. That is the only dependable control, and doing
it monthly would have caught this in weeks.

## IMPORTANT for Azure free tier users
Enable `server side retry` to prevent rate-limiting errors for Azure Cosmos DB for MongoDB operations. Follow link below for details.
https://learn.microsoft.com/en-us/azure/cosmos-db/mongodb/prevent-rate-limiting-errors  

## Obtain Alphatrak API Bearer Token & PetID
- Register and run your Alphatrak app on a mobile phone first.
- Install a packet capture app on your mobile. eg. Http traffic capture for iOS. PCAPdroid for andriod.
- Install the required certificate per the packet capture app instruction.
- Scan Alphatrak app to find the `api/GetPetActivityByDateWiseList` entry.
- Under `Request header`, find `Authorisation:bearer abc...`. "`abc...`" is your `at_token`. Do not include the word `bearer`.
- Under `Request body`, click json file. `PetId` is your `at_petid`.

## Hashing Nightscout API token
`ns_api_secret`  must be a SHA1 hash of an Access Token from Nightscout (Add new subject first in Nightscout's Admin Tools if required), e.g. your Access Token for a subject named Alphatrak might be `alphatrak-123456789abcde`.

Obtain your hash with
```
echo -n "alphatrak-123456789abcde" | sha1sum | cut -d ' ' -f 1
```
(use shasum instead of sha1sum on Mac)

which will print the hash (40 characters in length):
```
14c779d01a34ad1337ab59c2168e31b141eb2de6
```
You might also use an online tool to generate your hash, e.g. https://codebeautify.org/sha1-hash-generator

Credit to https://github.com/timoschlueter/nightscout-librelink-up

## Deployment
The uploader is one long running process. It opens no ports, serves no pages, writes no files and needs no database. It wakes every `uploader_interval` minutes, reads from Alphatrak and posts to Nightscout. Anything that can keep a small Python process alive will run it, so pick whichever of the following suits the hardware you already have.

* **API secret and token are passed as Environment Variables.** If you have security concerns, please stop using this script or fork this repository to make improvements. (Docker swarm mode may be required to use secrets.)

Keep your credentials in a file rather than on the command line, so they do not end up in your shell history:

```
cp .env.example .env
chmod 600 .env
```

Then fill in `.env`. The same file works for Docker, Docker Compose and systemd.

### Option 1. Docker
Image: https://hub.docker.com/r/imlovinit1019/nightscout-alphatrak-uploader

```
docker run -d \
  --name nightscout-alphatrak-uploader \
  --restart unless-stopped \
  --env-file .env \
  imlovinit1019/nightscout-alphatrak-uploader:latest
```

Follow it with `docker logs -f nightscout-alphatrak-uploader`. A healthy run prints the last BG Check date, the Zoetis response status and how many entries were uploaded.

Published tags are built for `linux/amd64`. On an arm host such as a Raspberry Pi, build the image yourself with `docker build -t nightscout-alphatrak-uploader .` and run that, or use Option 3.

### Option 2. Docker Compose
`docker-compose.yml` in this repository is ready to use once `.env` exists.

```
docker compose up -d
docker compose logs -f
```

It pulls the published image, restarts unless you stop it, and reads `.env`. To run your own changes instead, swap the `image:` line for `build: .` as noted in the file.

### Option 3. Portainer
`docker-compose-portainer.yml` is the Compose file adapted for a Portainer stack. Go to Stacks, Add stack, Web editor, paste it in, then supply the four required values under Environment variables, either one at a time or with `Load variables from .env file` using a filled in copy of `.env.example`.

Portainer substitutes those values into the `${...}` entries when it deploys and leaves the stack definition as written, so your token and API secret are not stored in the compose file itself.

Use that file rather than `docker-compose.yml`, which reads `env_file: .env`. A stack defined in the browser has no such file beside it.

If a required variable is missing, the container exits with `at_token required. Pass it as an Environment Variable.` and the restart policy will keep retrying, so check the stack logs if it will not stay up.

### Option 4. Python directly
The only dependency is `urllib3`. Python 3.11 or newer is required.

```
git clone https://github.com/ImLovinIt/nightscout-alphatrak-uploader.git
cd nightscout-alphatrak-uploader
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
set -a; . ./.env; set +a
python -u package/main.py
```

To keep it running after you log out, on a Raspberry Pi or any systemd machine, save this as `/etc/systemd/system/alphatrak-uploader.service`, adjusting the user and paths:

```
[Unit]
Description=Nightscout Alphatrak Uploader
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/opt/nightscout-alphatrak-uploader
EnvironmentFile=/opt/nightscout-alphatrak-uploader/.env
ExecStart=/opt/nightscout-alphatrak-uploader/.venv/bin/python -u package/main.py
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Then `sudo systemctl enable --now alphatrak-uploader`, and read the output with `journalctl -u alphatrak-uploader -f`.

### Option 5. Managed container hosts
Northflank, Fly.io, Railway, Koyeb and similar platforms will run the image, as will the Container Manager on a Synology NAS or the Docker plugin on unRAID.

Two things to watch for:

- Deploy it as a **worker or background service**, not a web service. The uploader listens on no port, so a web service plan may fail its health checks or idle the container to sleep.
- The published image is amd64 only, so either choose an amd64 machine type or point the platform at this repository and let it build.

Set the environment variables through the platform's own secrets or variables UI rather than baking them into an image.
