-- Admin dashboard read functions. service_role only - bypass RLS.

create function public.admin_user_count()
returns bigint
language sql
stable
security definer
set search_path = ''
as $$
    select count(*) from auth.users;
$$;

revoke all on function public.admin_user_count() from public, anon, authenticated;
grant execute on function public.admin_user_count() to service_role;

-- Verify action values first:
--   select payload->>'action', count(*) from auth.audit_log_entries group by 1 order by 2 desc;
create function public.admin_daily_auth_events(p_days integer default 30)
returns table (
    day date,
    signups bigint,
    logins bigint,
    logouts bigint
)
language sql
stable
security definer
set search_path = ''
as $$
    select
        (created_at at time zone 'utc')::date as day,
        count(*) filter (where payload ->> 'action' = 'user_signedup') as signups,
        count(*) filter (where payload ->> 'action' = 'login') as logins,
        count(*) filter (where payload ->> 'action' = 'logout') as logouts
    from auth.audit_log_entries
    where created_at >= (now() - make_interval(days => greatest(1, p_days)))
    group by 1
    order by 1;
$$;

revoke all on function public.admin_daily_auth_events(integer) from public, anon, authenticated;
grant execute on function public.admin_daily_auth_events(integer) to service_role;

-- Audit log list. email reads payload->>'actor_username'.
create function public.admin_recent_auth_events(p_limit integer default 50)
returns table (
    created_at timestamptz,
    action text,
    email text
)
language sql
stable
security definer
set search_path = ''
as $$
    select
        audit_log_entries.created_at,
        audit_log_entries.payload ->> 'action' as action,
        audit_log_entries.payload ->> 'actor_username' as email
    from auth.audit_log_entries
    order by audit_log_entries.created_at desc
    limit greatest(1, least(p_limit, 200));
$$;

revoke all on function public.admin_recent_auth_events(integer) from public, anon, authenticated;
grant execute on function public.admin_recent_auth_events(integer) to service_role;
