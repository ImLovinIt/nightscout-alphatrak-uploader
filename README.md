# Nightscout Alphatrak Uploader
Script written in python to periodically upload Zoetis Alphatrak glucose data to Nightscout.

*Only tested with Zoetis Alphatrak 3

## Configuration
The script takes the following environment variables
| Variable                 | Description                                                                                                                | Example                                  | Required |
|--------------------------|----------------------------------------------------------------------------------------------------------------------------|------------------------------------------|----------|
| at_token                 | Alphatrak Bearer Token (See below for details)                                                                                    | YGza5ertORghredgUOXAQw...(256 characters)    | X        |
| at_petid                 | Alphatrak Pet ID (See below for details)                                                                                   | 12345                                       | X        |
| ns_url                   | Hostname of the Nightscout instance with http:// or https:// and end with /                                                | https://nightscout.azurewebsites.net/    | X        |
| ns_api_secret            | SHA1 Hash of Nightscout access toke                                                                                        | 162f14de46149447c3338a8286223de407e3b2fa | X        |
| uploader_interval        | The time interval of running this script. Default to 30 mins.       | 30                                        |          |
| uploader_max_entries     | Maximum number of entries to upload every time. 0 to disable.                                                               | 0                                        |          |
| uploader_all_data        | Upload all available data.                                                                          | False                                    |          |


## IMPORTANT for Azure free tier users
Enable `server side retry` to prevent rate-limiting errors for Azure Cosmos DB for MongoDB operations. Follow link below for details.
https://learn.microsoft.com/en-us/azure/cosmos-db/mongodb/prevent-rate-limiting-errors  

## Obtain Alphatrak API Bearer Token & PetID
- Register and run your Alphatrak app on a mobile phone first.
- Install a packet capture app on your mobile. eg. Http traffic capture for iOS. PCAPdroid for andriod.
- Install the required certificate per the packet capture app instruction.
- Scan Alphatrak app to find the `api/GetPetActivityByDateWiseList` entry.
- Under `Request header`, find `Authorisation:bearer abc...`. "`abc...`" is your `at_token`.
- Under `Request body`, click json file. `PetId` is your `at_petid`.

## Hashing Nightscout API token
`ns_api_secret`  must be a SHA1 hash of an Access Token from Nightscout (Add new subject first in Nightscout's Admin Tools if required), e.g. your Access Token for a subject named Sisensing might be `sisensing-123456789abcde`.

Obtain your hash with
```
echo -n "sisensing-123456789abcde" | sha1sum | cut -d ' ' -f 1
```
(use shasum instead of sha1sum on Mac)

which will print the hash (40 characters in length):
```
14c779d01a34ad1337ab59c2168e31b141eb2de6
```
You might also use an online tool to generate your hash, e.g. https://codebeautify.org/sha1-hash-generator

## Deployment - Docker

Docker Hub
https://hub.docker.com/r/imlovinit1019/nightscout-alphatrak-uploader

* **API secret and token are passed as Environment Variables.** If you have security concerns, please stop using this script or fork this repository to make improvements. (Docker swarm mode may be required to use secrets.)
