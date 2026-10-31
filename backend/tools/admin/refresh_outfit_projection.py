"""Rebuild current outfit views from saved evaluations. No model calls or new jobs."""
import argparse
from app.repositories.factory import build_closet_repository
from app.outfits.store import build_store
from app.outfits.config import load_config
from app.outfits.service import OutfitLibrary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    scope=parser.add_mutually_exclusive_group(required=True)
    scope.add_argument('--user-id');scope.add_argument('--all-users',action='store_true')
    args=parser.parse_args()
    repo=build_closet_repository();store=build_store(repo)
    library=OutfitLibrary(repo,store,load_config())
    if not hasattr(store,'projection_state'):parser.error('The current projection requires the Supabase repository.')
    for uid in ([args.user_id] if args.user_id else store.users()):
        for _ in range(3):
            if library.refresh_projection(uid) is not False:break
        else:raise RuntimeError('Wardrobe kept changing during projection rebuild; retry later.')
        print(f'Current outfit projection ready: {uid}')

if __name__=='__main__':main()
