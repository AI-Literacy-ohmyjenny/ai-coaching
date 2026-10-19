-- AI 사용량 기록 / 비용 한도용 테이블과 함수
-- Supabase 대시보드 > SQL Editor 에 붙여넣고 Run 하세요. (여러 번 실행해도 안전합니다)

create table if not exists public.ai_usage (
  id bigserial primary key,
  created_at timestamptz not null default now(),
  ip_hash text not null,
  prompt_tokens integer not null default 0,
  completion_tokens integer not null default 0,
  cost_krw numeric(12,4) not null default 0
);

create index if not exists ai_usage_created_at_idx on public.ai_usage (created_at);

-- 외부(anon 키)에서 직접 읽거나 쓰지 못하도록 RLS 를 켭니다. 서버는 service_role 키로만 접근합니다.
alter table public.ai_usage enable row level security;

create or replace function public.ai_usage_summary(
  month_start timestamptz,
  hour_start timestamptz,
  ip_start timestamptz,
  ip text
) returns json
language sql
stable
as $$
  select json_build_object(
    'month_cost_krw', coalesce((select sum(cost_krw) from public.ai_usage where created_at >= month_start), 0),
    'month_calls',    (select count(*) from public.ai_usage where created_at >= month_start),
    'hour_calls',     (select count(*) from public.ai_usage where created_at >= hour_start),
    'ip_calls',       (select count(*) from public.ai_usage where created_at >= ip_start and ip_hash = ip)
  );
$$;

revoke all on function public.ai_usage_summary(timestamptz, timestamptz, timestamptz, text) from public, anon, authenticated;
grant execute on function public.ai_usage_summary(timestamptz, timestamptz, timestamptz, text) to service_role;

-- 학생 글 테이블(essays)도 같은 방식으로 외부 직접 접근을 막아 두는 것을 권장합니다.
-- alter table public.essays enable row level security;
