-- Outfit generation does not consume user_preferences. Recommendation ranking
-- reads preferences at request time, so profile/catalog edits must not erase the
-- already-published outfit projection.
begin;
drop trigger if exists preference_outfit_refresh on public.user_preferences;
commit;
notify pgrst,'reload schema';
