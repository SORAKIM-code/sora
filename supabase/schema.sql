-- ============================================================================
-- 밀매치(Military＋Match) — Supabase 스키마 · RLS · GRANT · Storage
--
-- 기능: 카탈로그 조회 / 로그인(Supabase Auth) / 활용 신청 접수·목록 조회 / 사진(첨부) 업로드
-- 원칙: 설정되지 않은 권한은 거부(deny-by-default). 모든 표에 RLS 를 켜고,
--       GRANT 는 필요한 표·열만 연다. 역할(role)·소속(org)은 본인이 바꿀 수 없다.
--
-- 실행: Supabase 대시보드 → SQL Editor 에 통째로 붙여 넣고 실행(새 프로젝트 기준, 한 번만).
-- 주의: service_role 키는 RLS 를 건너뛴다. Vercel 서버 함수에서도 사용자 요청은
--       사용자 JWT(또는 anon 키)로 Supabase 를 불러야 이 정책이 적용된다.
-- ============================================================================

-- 정책에서 쓰는 보조 함수는 API 로 노출되지 않는 private 스키마에 둔다.
create schema if not exists private;

-- ----------------------------------------------------------------------------
-- 1. 사용자 프로필 (auth.users 와 1:1)
-- ----------------------------------------------------------------------------
create table public.profiles (
  id           uuid primary key references auth.users (id) on delete cascade,
  display_name text not null default '' check (char_length(display_name) <= 50),
  org          text check (char_length(org) <= 100),            -- 소속 기관: 관리자만 변경
  role         text not null default 'researcher'
               check (role in ('researcher', 'operator', 'data_owner', 'admin')),
  department   text check (char_length(department) <= 100),     -- 데이터 소관 부서(data_owner)
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- 2. 카탈로그 (엑셀 한 행 = 한 행)
-- ----------------------------------------------------------------------------
create table public.catalogs (
  id                  text primary key check (id ~ '^[A-Za-z0-9가-힣][A-Za-z0-9가-힣_.-]{0,39}$'),
  version             integer not null default 1 check (version >= 1),
  status              text not null default 'draft' check (status in ('draft', 'approved', 'withdrawn')),
  title               text not null check (char_length(title) between 1 and 200),
  description         text,
  domain              text not null,
  access_level        text not null check (access_level in ('공개', '거점승인', '제한')),
  keywords            text[] not null default '{}',
  data_items          text[] not null default '{}',             -- 엑셀 '항목 정의'
  data_type           text,
  structure           text check (structure in ('정형', '반정형', '비정형')),
  preprocessed        text check (preprocessed in ('있음', '없음')),
  preprocess_detail   text,
  size                text,                                     -- 데이터 용량(예: 약 180MB)
  file_count          text,                                     -- 파일 개수(예: 96개)
  period_start        text,
  period_end          text,
  department          text,                                     -- 소관 부서
  procedure           text,
  place_restriction   text,
  purpose_restriction text,
  image_path          text,                                     -- storage 'catalog-images' 안의 경로
  extra               jsonb not null default '{}'::jsonb,       -- 그 밖의 엑셀 열
  source              jsonb,                                    -- 근거 위치 {file, sheet, row, cols}
  reviewed_by         uuid references auth.users (id),
  reviewed_at         timestamptz,
  updated_by          uuid references auth.users (id),
  updated_at          timestamptz not null default now()
);
create index catalogs_visible_idx on public.catalogs (status, access_level, domain);

-- ----------------------------------------------------------------------------
-- 3. 열람 권한 (사용자 또는 기관 × 연구 목적 × 공개 범위 × 분야 × 기간)
-- ----------------------------------------------------------------------------
create table public.access_grants (
  id         bigint generated always as identity primary key,
  user_id    uuid references auth.users (id) on delete cascade,
  org        text,
  purpose    text not null check (char_length(purpose) between 1 and 100),
  levels     text[] not null check (levels <@ array['공개', '거점승인', '제한']::text[] and cardinality(levels) > 0),
  domains    text[] not null default array['*']::text[],          -- '*' = 전체 분야
  valid_from date not null,
  valid_to   date not null,
  revoked_at timestamptz,
  created_by uuid references auth.users (id) default auth.uid(),
  created_at timestamptz not null default now(),
  check ((user_id is null) <> (org is null)),                     -- 사용자 또는 기관 중 하나
  check (valid_from <= valid_to)
);
create index access_grants_user_idx on public.access_grants (user_id) where revoked_at is null;
create index access_grants_org_idx on public.access_grants (org) where revoked_at is null;

-- ----------------------------------------------------------------------------
-- 4. 활용 신청 (신청 접수·목록 조회)
-- ----------------------------------------------------------------------------
create table public.applications (
  id            uuid primary key default gen_random_uuid(),
  applicant_id  uuid not null default auth.uid() references auth.users (id) on delete cascade,
  catalog_id    text not null references public.catalogs (id),
  purpose       text not null check (char_length(purpose) between 5 and 2000),
  plan          text check (char_length(plan) <= 5000),
  wanted_period text check (char_length(wanted_period) <= 100),
  contact       text check (char_length(contact) <= 200),
  status        text not null default 'submitted'
                check (status in ('submitted', 'reviewing', 'approved', 'rejected', 'withdrawn')),
  review_note   text check (char_length(review_note) <= 2000),
  reviewed_by   uuid references auth.users (id),
  reviewed_at   timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index applications_applicant_idx on public.applications (applicant_id, created_at desc);
create index applications_status_idx on public.applications (status, created_at desc);
create index applications_catalog_idx on public.applications (catalog_id);

-- ----------------------------------------------------------------------------
-- 5. 신청 첨부 사진 (파일은 Storage 'application-files', 여기는 목록)
--    경로 규칙: {신청자 uid}/{신청 id}/{파일 이름}
-- ----------------------------------------------------------------------------
create table public.application_files (
  id             uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.applications (id) on delete cascade,
  owner_id       uuid not null default auth.uid() references auth.users (id) on delete cascade,
  storage_path   text not null unique,
  content_type   text not null check (content_type in ('image/jpeg', 'image/png', 'image/webp')),
  size_bytes     integer not null check (size_bytes between 1 and 5242880),   -- 5MB
  created_at     timestamptz not null default now(),
  check (storage_path like owner_id::text || '/' || application_id::text || '/%')
);
create index application_files_app_idx on public.application_files (application_id);

-- ----------------------------------------------------------------------------
-- 6. 감사로그 (트리거로만 기록, 사용자가 직접 쓰지 못함)
-- ----------------------------------------------------------------------------
create table public.audit_logs (
  id      bigint generated always as identity primary key,
  ts      timestamptz not null default now(),
  user_id uuid default auth.uid(),
  event   text not null,
  target  text,
  detail  jsonb not null default '{}'::jsonb
);
create index audit_logs_ts_idx on public.audit_logs (ts desc);


-- ============================================================================
-- 보조 함수 (security definer: RLS 안에서 profiles/access_grants 를 재귀 없이 읽는다)
-- ============================================================================
create or replace function private.my_role() returns text
language sql stable security definer set search_path = '' as $$
  select p.role from public.profiles p where p.id = (select auth.uid())
$$;

create or replace function private.my_department() returns text
language sql stable security definer set search_path = '' as $$
  select p.department from public.profiles p where p.id = (select auth.uid())
$$;

create or replace function private.is_admin() returns boolean
language sql stable security definer set search_path = '' as $$
  select coalesce(private.my_role() = 'admin', false)
$$;

-- 거점 운영부서·서비스 운영자 (권한 관리, 신청 처리, 로그 열람)
create or replace function private.is_staff() returns boolean
language sql stable security definer set search_path = '' as $$
  select coalesce(private.my_role() in ('operator', 'admin'), false)
$$;

-- 이 사용자가 승인된 카탈로그를 열람할 수 있는가: 공개 / 담당자 / 소관 부서 / 유효한 열람 권한
create or replace function private.can_view_catalog(p_access text, p_domain text, p_department text)
returns boolean
language sql stable security definer set search_path = '' as $$
  select
    p_access = '공개'
    or private.is_staff()
    or (private.my_role() = 'data_owner' and p_department is not distinct from private.my_department())
    or exists (
      select 1
      from public.access_grants g
      left join public.profiles me on me.id = (select auth.uid())
      where (select auth.uid()) is not null
        and (g.user_id = (select auth.uid()) or (g.org is not null and g.org = me.org))
        and g.revoked_at is null
        and current_date between g.valid_from and g.valid_to
        and p_access = any (g.levels)
        and ('*' = any (g.domains) or p_domain = any (g.domains))
    )
$$;


-- ============================================================================
-- 트리거
-- ============================================================================
-- 가입하면 프로필을 만든다. 역할은 항상 researcher (가입 메타데이터의 역할 값은 믿지 않는다).
create or replace function private.handle_new_user() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  insert into public.profiles (id, display_name)
  values (new.id, left(coalesce(new.raw_user_meta_data ->> 'display_name', ''), 50));
  return new;
end
$$;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function private.handle_new_user();

-- 프로필: 본인은 이름만, 역할·소속·부서는 관리자만 바꾼다.
-- 로그인 사용자 없이 실행되는 경우(SQL Editor, service_role 서버 작업)는 신뢰된 경로로 보고 통과시킨다.
create or replace function private.profiles_guard() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if (select auth.uid()) is not null
     and not private.is_admin()
     and (new.role, new.org, new.department) is distinct from (old.role, old.org, old.department) then
    raise exception '역할·소속·부서는 서비스 운영자만 바꿀 수 있습니다.' using errcode = '42501';
  end if;
  if new.id <> old.id then
    raise exception 'id 는 바꿀 수 없습니다.' using errcode = '42501';
  end if;
  new.updated_at := now();
  return new;
end
$$;
create trigger profiles_guard
  before update on public.profiles
  for each row execute function private.profiles_guard();

-- 카탈로그: 수정자·시각 기록, 승인 시 검수자 기록
create or replace function private.catalogs_stamp() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  new.updated_by := (select auth.uid());
  new.updated_at := now();
  if new.status = 'approved' and (tg_op = 'INSERT' or old.status is distinct from 'approved') then
    new.reviewed_by := (select auth.uid());
    new.reviewed_at := now();
  end if;
  return new;
end
$$;
create trigger catalogs_stamp
  before insert or update on public.catalogs
  for each row execute function private.catalogs_stamp();

-- 신청: 신청자는 '접수' 상태일 때 철회만, 담당자는 상태·처리 의견만 바꾼다.
create or replace function private.applications_guard() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if (new.applicant_id, new.catalog_id, new.purpose, new.plan, new.wanted_period, new.contact, new.created_at)
     is distinct from
     (old.applicant_id, old.catalog_id, old.purpose, old.plan, old.wanted_period, old.contact, old.created_at) then
    raise exception '신청 내용은 바꿀 수 없습니다. 철회 후 다시 신청하세요.' using errcode = '42501';
  end if;
  if (select auth.uid()) is null then
    null;  -- SQL Editor · service_role 서버 작업
  elsif private.is_staff() then
    if new.status is distinct from old.status or new.review_note is distinct from old.review_note then
      new.reviewed_by := (select auth.uid());
      new.reviewed_at := now();
    end if;
  elsif old.applicant_id = (select auth.uid()) then
    if not (old.status = 'submitted' and new.status = 'withdrawn')
       or new.review_note is distinct from old.review_note then
      raise exception '접수 상태의 신청만 철회할 수 있습니다.' using errcode = '42501';
    end if;
  else
    raise exception '이 신청을 바꿀 권한이 없습니다.' using errcode = '42501';
  end if;
  new.updated_at := now();
  return new;
end
$$;
create trigger applications_guard
  before update on public.applications
  for each row execute function private.applications_guard();

-- 감사로그: 신청·카탈로그·열람 권한의 변경을 남긴다(신청 본문은 남기지 않음).
create or replace function private.write_audit() returns trigger
language plpgsql security definer set search_path = '' as $$
declare
  rec jsonb := to_jsonb(coalesce(new, old));
begin
  insert into public.audit_logs (user_id, event, target, detail)
  values (
    (select auth.uid()),
    tg_table_name || '_' || lower(tg_op),
    rec ->> 'id',
    jsonb_strip_nulls(jsonb_build_object(
      'status', rec ->> 'status',
      'old_status', case when tg_op = 'UPDATE' then to_jsonb(old) ->> 'status' end,
      'catalog_id', rec ->> 'catalog_id',
      'version', rec ->> 'version',
      'revoked_at', rec ->> 'revoked_at'))
  );
  return coalesce(new, old);
end
$$;
create trigger applications_audit after insert or update on public.applications
  for each row execute function private.write_audit();
create trigger catalogs_audit after insert or update or delete on public.catalogs
  for each row execute function private.write_audit();
create trigger access_grants_audit after insert or update on public.access_grants
  for each row execute function private.write_audit();


-- ============================================================================
-- RLS 켜기
-- ============================================================================
alter table public.profiles          enable row level security;
alter table public.catalogs          enable row level security;
alter table public.access_grants     enable row level security;
alter table public.applications      enable row level security;
alter table public.application_files enable row level security;
alter table public.audit_logs        enable row level security;


-- ============================================================================
-- RLS 정책
-- ============================================================================
-- profiles: 본인과 담당자만 조회, 본인(이름) 또는 관리자만 수정. 생성은 트리거, 삭제는 auth 에서.
create policy profiles_select on public.profiles
  for select to authenticated
  using (id = (select auth.uid()) or private.is_staff());
create policy profiles_update on public.profiles
  for update to authenticated
  using (id = (select auth.uid()) or private.is_admin())
  with check (id = (select auth.uid()) or private.is_admin());

-- catalogs: 승인된 것 중 열람 가능한 것만. 담당자는 전체, 소관 부서는 자기 부서 초안까지.
create policy catalogs_select on public.catalogs
  for select to anon, authenticated
  using (
    (status = 'approved' and private.can_view_catalog(access_level, domain, department))
    or private.is_staff()
    or (private.my_role() = 'data_owner' and department is not distinct from private.my_department())
  );
create policy catalogs_insert on public.catalogs
  for insert to authenticated
  with check (
    private.is_admin()
    or (private.my_role() = 'data_owner' and department is not distinct from private.my_department())
  );
create policy catalogs_update on public.catalogs
  for update to authenticated
  using (
    private.is_admin()
    or (private.my_role() = 'data_owner' and department is not distinct from private.my_department())
  )
  with check (
    private.is_admin()
    or (private.my_role() = 'data_owner' and department is not distinct from private.my_department())
  );
create policy catalogs_delete on public.catalogs
  for delete to authenticated
  using (private.is_admin());          -- 보통은 삭제 대신 status = 'withdrawn'

-- access_grants: 본인 권한은 조회, 관리·회수는 담당자. 삭제는 없음(revoked_at 으로 회수).
create policy access_grants_select on public.access_grants
  for select to authenticated
  using (user_id = (select auth.uid()) or private.is_staff());
create policy access_grants_insert on public.access_grants
  for insert to authenticated
  with check (private.is_staff());
create policy access_grants_update on public.access_grants
  for update to authenticated
  using (private.is_staff())
  with check (private.is_staff());

-- applications: 로그인한 사용자가 열람 가능한 승인 카탈로그에만 신청.
--               본인 신청과 담당자, 해당 카탈로그 소관 부서만 조회.
create policy applications_insert on public.applications
  for insert to authenticated
  with check (
    applicant_id = (select auth.uid())
    and status = 'submitted'
    and exists (
      select 1 from public.catalogs c
      where c.id = catalog_id
        and c.status = 'approved'
        and private.can_view_catalog(c.access_level, c.domain, c.department)
    )
  );
create policy applications_select on public.applications
  for select to authenticated
  using (
    applicant_id = (select auth.uid())
    or private.is_staff()
    or (private.my_role() = 'data_owner' and exists (
          select 1 from public.catalogs c
          where c.id = catalog_id and c.department is not distinct from private.my_department()))
  );
create policy applications_update on public.applications
  for update to authenticated
  using (applicant_id = (select auth.uid()) or private.is_staff())
  with check (applicant_id = (select auth.uid()) or private.is_staff());
-- 삭제 정책 없음: 신청은 철회(status = 'withdrawn')로 남긴다.

-- application_files: 본인 신청(접수 상태)에만 올리고, 본인·담당자만 조회, 본인만 삭제.
create policy application_files_insert on public.application_files
  for insert to authenticated
  with check (
    owner_id = (select auth.uid())
    and exists (
      select 1 from public.applications a
      where a.id = application_id and a.applicant_id = (select auth.uid()) and a.status = 'submitted')
  );
create policy application_files_select on public.application_files
  for select to authenticated
  using (owner_id = (select auth.uid()) or private.is_staff());
create policy application_files_delete on public.application_files
  for delete to authenticated
  using (
    owner_id = (select auth.uid())
    and exists (
      select 1 from public.applications a
      where a.id = application_id and a.status = 'submitted')
  );

-- audit_logs: 담당자만 조회. 쓰기는 트리거(security definer)만.
create policy audit_logs_select on public.audit_logs
  for select to authenticated
  using (private.is_staff());


-- ============================================================================
-- GRANT (표·열 단위로 필요한 것만)
-- Supabase 는 기본으로 public 의 표를 anon·authenticated 에 모두 열어 두므로 먼저 거둔다.
-- ============================================================================
revoke all on all tables in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
alter default privileges in schema public revoke all on tables from anon, authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;
alter default privileges in schema public revoke all on functions from anon, authenticated;

grant usage on schema public to anon, authenticated;

-- 카탈로그: 누구나 조회(행은 RLS 가 거름), 쓰기는 로그인 사용자(관리자·소관 부서만 RLS 통과)
grant select on public.catalogs to anon, authenticated;
grant insert, update, delete on public.catalogs to authenticated;

-- 프로필: 조회, 이름·역할·소속·부서 수정(역할·소속·부서는 트리거가 관리자만 허용)
grant select on public.profiles to authenticated;
grant update (display_name, org, role, department) on public.profiles to authenticated;

-- 열람 권한
grant select on public.access_grants to authenticated;
grant insert (user_id, org, purpose, levels, domains, valid_from, valid_to) on public.access_grants to authenticated;
grant update (revoked_at, valid_to) on public.access_grants to authenticated;

-- 신청: 신청자는 내용만 넣는다(상태·처리 결과·신청자 id 는 넣을 수 없음)
grant select on public.applications to authenticated;
grant insert (catalog_id, purpose, plan, wanted_period, contact) on public.applications to authenticated;
grant update (status, review_note) on public.applications to authenticated;

-- 첨부 사진 목록
grant select, delete on public.application_files to authenticated;
grant insert (application_id, storage_path, content_type, size_bytes) on public.application_files to authenticated;

-- 감사로그: 조회만
grant select on public.audit_logs to authenticated;

-- private 스키마 보조 함수: 정책 평가에만 쓰도록 실행 권한만 준다(API 로는 노출되지 않음).
revoke all on schema private from public;
revoke execute on all functions in schema private from public, anon, authenticated;
grant usage on schema private to anon, authenticated;
grant execute on function private.my_role()                        to anon, authenticated;
grant execute on function private.my_department()                  to anon, authenticated;
grant execute on function private.is_admin()                       to anon, authenticated;
grant execute on function private.is_staff()                       to anon, authenticated;
grant execute on function private.can_view_catalog(text, text, text) to anon, authenticated;


-- ============================================================================
-- Storage: 버킷과 정책
--   catalog-images   : 카탈로그 대표 이미지. 경로 {카탈로그 id}/{파일}. 열람 가능한 카탈로그의 그림만 보임.
--   application-files: 신청 첨부 사진. 경로 {신청자 uid}/{신청 id}/{파일}. 비공개.
-- 둘 다 비공개 버킷(public = false)이라 공개 URL 이 없다. 화면에서는 signed URL 이나 SDK download 로 받는다.
-- ============================================================================
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values
  ('catalog-images',    'catalog-images',    false, 5242880, array['image/jpeg', 'image/png', 'image/webp']),
  ('application-files', 'application-files', false, 5242880, array['image/jpeg', 'image/png', 'image/webp'])
on conflict (id) do nothing;

-- 카탈로그 이미지: 그 카탈로그를 볼 수 있으면 그림도 볼 수 있다(catalogs 의 RLS 가 그대로 적용됨).
create policy "catalog images: read when catalog visible" on storage.objects
  for select to anon, authenticated
  using (
    bucket_id = 'catalog-images'
    and exists (select 1 from public.catalogs c where c.id = (storage.foldername(name))[1])
  );
create policy "catalog images: admin upload" on storage.objects
  for insert to authenticated
  with check (bucket_id = 'catalog-images' and private.is_admin());
create policy "catalog images: admin update" on storage.objects
  for update to authenticated
  using (bucket_id = 'catalog-images' and private.is_admin())
  with check (bucket_id = 'catalog-images' and private.is_admin());
create policy "catalog images: admin delete" on storage.objects
  for delete to authenticated
  using (bucket_id = 'catalog-images' and private.is_admin());

-- 신청 첨부: 본인 폴더, 본인의 '접수' 상태 신청 폴더에만 올린다. 덮어쓰기(update) 정책은 두지 않는다.
create policy "application files: owner upload" on storage.objects
  for insert to authenticated
  with check (
    bucket_id = 'application-files'
    and (storage.foldername(name))[1] = (select auth.uid())::text
    and exists (
      select 1 from public.applications a
      where a.id::text = (storage.foldername(name))[2]
        and a.applicant_id = (select auth.uid())
        and a.status = 'submitted')
  );
create policy "application files: owner or staff read" on storage.objects
  for select to authenticated
  using (
    bucket_id = 'application-files'
    and ((storage.foldername(name))[1] = (select auth.uid())::text or private.is_staff())
  );
create policy "application files: owner delete" on storage.objects
  for delete to authenticated
  using (
    bucket_id = 'application-files'
    and (storage.foldername(name))[1] = (select auth.uid())::text
  );


-- ============================================================================
-- 첫 관리자 지정 (가입 후 한 번, SQL Editor 에서 실행 — 이메일을 바꿔서)
-- ============================================================================
-- update public.profiles set role = 'admin', org = '(기관명)'
--   where id = (select id from auth.users where email = 'admin@example.com');
