import os
from google.cloud import logging

client = logging.Client(project='placementpilot-506011')
filter_str = 'resource.type="cloud_run_revision" AND resource.labels.service_name="placementpilot-backend" AND timestamp>="2026-08-21T04:42:00Z" AND timestamp<="2026-08-21T04:43:00Z"'
for entry in client.list_entries(filter_=filter_str):
    print(entry.payload)
