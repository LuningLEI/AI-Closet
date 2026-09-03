create table if not exists public.recognition_jobs (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    clothing_item_id uuid not null references public.clothing_items(id) on delete cascade,
    filename text not null,
    image_url text not null,
    image_path text,
    status text not null default 'queued',
    attempts integer not null default 0,
    last_error text,
    leased_at timestamptz,
    next_run_at timestamptz,
    dead_lettered_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.recognition_jobs
    add column if not exists user_id uuid;

alter table public.recognition_jobs
    add column if not exists leased_at timestamptz;

alter table public.recognition_jobs
    add column if not exists next_run_at timestamptz;

alter table public.recognition_jobs
    add column if not exists dead_lettered_at timestamptz;

do $$
begin
    if exists (
        select 1 from pg_constraint where conname = 'recognition_jobs_status_check'
    ) then
        alter table public.recognition_jobs
            drop constraint recognition_jobs_status_check;
    end if;
end $$;

alter table public.recognition_jobs
    add constraint recognition_jobs_status_check
    check (status in ('queued', 'processing', 'complete', 'failed', 'dead_letter'));

create index if not exists recognition_jobs_status_created_at_idx
    on public.recognition_jobs (status, created_at);

create index if not exists recognition_jobs_clothing_item_id_idx
    on public.recognition_jobs (clothing_item_id);

create index if not exists recognition_jobs_user_status_created_at_idx
    on public.recognition_jobs (user_id, status, created_at);

create index if not exists recognition_jobs_status_next_run_at_idx
    on public.recognition_jobs (status, next_run_at);

alter table public.recognition_jobs enable row level security;

drop policy if exists recognition_jobs_owner_access on public.recognition_jobs;
create policy recognition_jobs_owner_access
    on public.recognition_jobs
    for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

create or replace function public.claim_recognition_jobs(
    batch_limit integer default 3,
    max_attempts integer default 3,
    job_timeout_seconds integer default 120
)
returns setof public.recognition_jobs
language plpgsql
as $$
begin
    update public.recognition_jobs
    set
        status = case
            when attempts >= max_attempts then 'dead_letter'
            else 'failed'
        end,
        last_error = coalesce(last_error, 'Recognition job timed out.'),
        next_run_at = case
            when attempts >= max_attempts then null
            else now()
        end,
        dead_lettered_at = case
            when attempts >= max_attempts then now()
            else dead_lettered_at
        end,
        updated_at = now()
    where status = 'processing'
        and leased_at is not null
        and leased_at < now() - make_interval(secs => job_timeout_seconds);

    update public.recognition_jobs
    set
        status = 'dead_letter',
        dead_lettered_at = coalesce(dead_lettered_at, now()),
        updated_at = now()
    where status = 'failed'
        and attempts >= max_attempts;

    return query
    update public.recognition_jobs
    set
        status = 'processing',
        attempts = attempts + 1,
        leased_at = now(),
        updated_at = now()
    where id in (
        select id
        from public.recognition_jobs
        where status in ('queued', 'failed')
            and attempts < max_attempts
            and (next_run_at is null or next_run_at <= now())
        order by created_at
        for update skip locked
        limit batch_limit
    )
    returning *;
end;
$$;
