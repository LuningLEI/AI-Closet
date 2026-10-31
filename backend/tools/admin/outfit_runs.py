"""Inspect/pin outfit runs and preview safe raw-usage compaction. Never calls models."""
import argparse
import json
from app.repositories.factory import build_closet_repository
from app.outfits.store import build_store


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--user-id',required=True)
    p.add_argument('--pin',metavar='RUN_ID');p.add_argument('--reason',default='Protected experiment')
    p.add_argument('--compact-usage',action='store_true');p.add_argument('--apply',action='store_true')
    args=p.parse_args()
    if args.apply and not args.compact_usage:p.error('--apply requires --compact-usage')
    if args.pin and args.compact_usage:p.error('Choose pin or compact, not both')
    store=build_store(build_closet_repository())
    if args.pin:
        if not store.pin_run(args.user_id,args.pin,args.reason):p.error('Run not found for this user')
        result={'run_id':args.pin,'pinned':True}
    elif args.compact_usage:
        result={'dry_run':not args.apply,'affected_calls':store.compact_usage(args.user_id,args.apply)}
    else:result=store.run_report(args.user_id)
    print(json.dumps(result,ensure_ascii=False,indent=2,default=str))

if __name__=='__main__':main()
