"""User-approved labels and optimistic writes shared by image/recognition workflows."""
from datetime import datetime, timezone
from uuid import uuid4
LABEL_FIELDS = ('category','subtype','color','season','style','occasion','recognition_summary','material','length','sleeve_length')
COMPARE_FIELDS = LABEL_FIELDS + ('image_path','recognition_status','recognition_source','metadata')

def confirmation(values):
    return {'revision':str(uuid4()),'confirmed_at':datetime.now(timezone.utc).isoformat(),
            'labels':{key:values.get(key) for key in LABEL_FIELDS}}
