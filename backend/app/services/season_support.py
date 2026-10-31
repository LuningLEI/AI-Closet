"""Canonical four-season labels; legacy all-season means all four selections."""
SEASONS = ['Spring', 'Summer', 'Fall', 'Winter']

def normalize_seasons(value):
    tokens = value.split(',') if isinstance(value,str) else value or []
    normalized = set()
    for token in tokens:
        for part in str(token).split(','):
            key=part.strip().lower()
            if key in {'all-season','all season','all seasons','year-round','year round'}:
                return SEASONS.copy()
            name={'spring':'Spring','summer':'Summer','fall':'Fall','autumn':'Fall','winter':'Winter'}.get(key)
            if name:normalized.add(name)
    return [s for s in SEASONS if s in normalized] or SEASONS.copy()


def normalize_user_seasons(value):
    tokens=value.split(',') if isinstance(value,str) else value or []
    custom=[];standard=[]
    aliases={'spring':'Spring','summer':'Summer','fall':'Fall','autumn':'Fall','winter':'Winter'}
    for token in tokens:
        label=str(token).strip()
        if not label:continue
        key=label.lower()
        if key in {'all-season','all season','all seasons','year-round','year round'}:
            standard=SEASONS.copy();continue
        if key in aliases:
            if aliases[key] not in standard:standard.append(aliases[key])
        elif label not in custom:custom.append(label)
    ordered=[season for season in SEASONS if season in standard]
    return ordered+custom or SEASONS.copy()
