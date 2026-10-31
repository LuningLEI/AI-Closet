-- Promote simulation-selected Taste defaults and rebuild existing projections.
-- Feedback, explicit preferences, outfits and wear history are preserved.

alter table public.user_taste_profiles
  alter column algorithm_version set default 'taste-profile-v2';

update public.user_taste_profiles
   set source_version = source_version + 1,
       updated_at = now()
 where algorithm_version is distinct from 'taste-profile-v2';
