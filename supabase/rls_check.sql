-- ============================================================================
-- schema.sql 의 RLS 점검. SQL Editor 에서 통째로 실행한다.
-- 시험용 사용자·자료를 만든 뒤 역할을 바꿔 가며 확인하고, 마지막에 전부 되돌린다(rollback).
-- 결과: 맨 아래 표에 항목마다 ok = true 가 나와야 한다.
-- ============================================================================
begin;

create temp table rls_result (step text, ok boolean) on commit drop;
grant all on rls_result to anon, authenticated;

-- 시험 사용자(가입 트리거가 profiles 를 researcher 로 만든다)
insert into auth.users (id, email) values
  ('00000000-0000-0000-0000-0000000000a1', 'rls-researcher@test.local'),
  ('00000000-0000-0000-0000-0000000000a2', 'rls-other@test.local'),
  ('00000000-0000-0000-0000-0000000000a3', 'rls-admin@test.local');
update public.profiles set role = 'admin' where id = '00000000-0000-0000-0000-0000000000a3';

insert into public.catalogs (id, status, title, domain, access_level) values
  ('RLS-PUB', 'approved', '공개 카탈로그', '차량', '공개'),
  ('RLS-HUB', 'approved', '거점승인 카탈로그', '차량', '거점승인'),
  ('RLS-RES', 'approved', '제한 카탈로그', '차량', '제한'),
  ('RLS-DRAFT', 'draft', '검수 전 카탈로그', '차량', '공개');
insert into public.access_grants (user_id, purpose, levels, domains, valid_from, valid_to) values
  ('00000000-0000-0000-0000-0000000000a1', '시험', array['공개', '거점승인'], array['*'], current_date - 1, current_date + 30);

-- ── 로그인하지 않은 방문자(anon) ──
set local role anon;
set local request.jwt.claims = '{"role":"anon"}';
insert into rls_result select 'anon: 공개·승인 카탈로그만 보임',
  (select array_agg(id order by id) from public.catalogs where id like 'RLS-%') = array['RLS-PUB'];
do $$ begin
  perform 1 from public.applications;
  insert into rls_result values ('anon: 신청 표 접근 거부', false);
exception when insufficient_privilege then insert into rls_result values ('anon: 신청 표 접근 거부', true);
end $$;
reset role;

-- ── 연구자 a1 (공개·거점승인 권한) ──
set local role authenticated;
set local request.jwt.claims = '{"sub":"00000000-0000-0000-0000-0000000000a1","role":"authenticated"}';
insert into rls_result select 'a1: 제한·초안은 안 보임',
  (select array_agg(id order by id) from public.catalogs where id like 'RLS-%') = array['RLS-HUB', 'RLS-PUB'];
insert into public.applications (catalog_id, purpose) values ('RLS-HUB', '시험용 활용 신청입니다');
insert into rls_result select 'a1: 신청 접수됨(상태 submitted)',
  (select status from public.applications where catalog_id = 'RLS-HUB') = 'submitted';
do $$ begin
  insert into public.applications (catalog_id, purpose) values ('RLS-RES', '제한 자료에 신청');
  insert into rls_result values ('a1: 제한 카탈로그 신청 거부', false);
exception when others then insert into rls_result values ('a1: 제한 카탈로그 신청 거부', true);
end $$;
do $$ begin
  update public.profiles set role = 'admin' where id = '00000000-0000-0000-0000-0000000000a1';
  insert into rls_result values ('a1: 스스로 관리자 되기 거부', false);
exception when others then insert into rls_result values ('a1: 스스로 관리자 되기 거부', true);
end $$;
do $$ begin
  update public.applications set status = 'approved' where catalog_id = 'RLS-HUB';
  insert into rls_result values ('a1: 스스로 승인 거부', false);
exception when others then insert into rls_result values ('a1: 스스로 승인 거부', true);
end $$;
update public.applications set status = 'withdrawn' where catalog_id = 'RLS-HUB';
insert into rls_result select 'a1: 본인 신청 철회 가능',
  (select status from public.applications where catalog_id = 'RLS-HUB') = 'withdrawn';
reset role;

-- ── 다른 연구자 a2 (권한 없음) ──
set local role authenticated;
set local request.jwt.claims = '{"sub":"00000000-0000-0000-0000-0000000000a2","role":"authenticated"}';
insert into rls_result select 'a2: 남의 신청은 안 보임', (select count(*) from public.applications) = 0;
insert into rls_result select 'a2: 공개 카탈로그만 보임',
  (select array_agg(id order by id) from public.catalogs where id like 'RLS-%') = array['RLS-PUB'];
insert into rls_result select 'a2: 감사로그 안 보임', (select count(*) from public.audit_logs) = 0;
reset role;

-- ── 관리자 a3 ──
set local role authenticated;
set local request.jwt.claims = '{"sub":"00000000-0000-0000-0000-0000000000a3","role":"authenticated"}';
insert into rls_result select 'a3: 모든 신청 조회', (select count(*) from public.applications) >= 1;
insert into rls_result select 'a3: 감사로그 조회', (select count(*) from public.audit_logs) >= 1;
reset role;

select * from rls_result;
rollback;
