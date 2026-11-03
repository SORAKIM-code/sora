-- ============================================================================
-- Storage 'attachments' 버킷: 로그인한 사용자만 업로드
--
-- 경로 규칙: {로그인 사용자 uid}/{파일 이름}   예) 3f1c…/report.pdf
--   → 다른 사람 폴더에는 올릴 수 없고, 로그인하지 않은 사용자(anon)는 아예 올릴 수 없다.
-- 덮어쓰기(update) 정책은 두지 않는다. 같은 경로에 다시 올리면(upsert) 거부되므로 파일 이름을 새로 정한다.
-- SQL Editor 에서 실행. 이미 버킷이 있으면 버킷 만들기는 건너뛴다.
-- ============================================================================

-- 1) 비공개 버킷(공개 URL 없음). 크기·형식 제한은 필요에 맞게 조정한다.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('attachments', 'attachments', false, 10485760,                -- 10MB
        array['image/jpeg', 'image/png', 'image/webp', 'application/pdf'])
on conflict (id) do nothing;

-- 2) 업로드: 로그인한 사용자가 자기 uid 폴더에만
create policy "attachments: authenticated upload own folder"
  on storage.objects
  for insert
  to authenticated
  with check (
    bucket_id = 'attachments'
    and (storage.foldername(name))[1] = (select auth.uid())::text
  );

-- 3) 조회·내려받기: 본인 파일만 (비공개 버킷이라 이 정책이 없으면 올린 사람도 못 받는다)
create policy "attachments: owner read"
  on storage.objects
  for select
  to authenticated
  using (
    bucket_id = 'attachments'
    and (storage.foldername(name))[1] = (select auth.uid())::text
  );

-- 4) 삭제: 본인 파일만
create policy "attachments: owner delete"
  on storage.objects
  for delete
  to authenticated
  using (
    bucket_id = 'attachments'
    and (storage.foldername(name))[1] = (select auth.uid())::text
  );

-- anon 에 대한 정책은 만들지 않는다 → 로그인하지 않은 요청은 업로드·조회·삭제 모두 거부.
-- (담당자도 보게 하려면 3) 의 using 에 'or private.is_staff()' 를 더한다. schema.sql 의 함수 사용)

-- ----------------------------------------------------------------------------
-- 클라이언트에서 올리는 예(supabase-js, 로그인 후):
--   const { data: { user } } = await supabase.auth.getUser();
--   await supabase.storage.from('attachments').upload(`${user.id}/${crypto.randomUUID()}.pdf`, file);
-- ----------------------------------------------------------------------------
