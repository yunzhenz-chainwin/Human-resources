-- =============================================================================
-- candidates_seed.sql
-- -----------------------------------------------------------------------------
-- 用途：TalentHub 人才主檔種子資料。植入 10 筆虛構人才（含學歷、經歷、技能、
--       語言、證照）與技能字典，供開發／測試環境使用。全部資料為虛構，僅供
--       功能驗證，不對應任何真實個人。
--
-- 執行方式：
--     psql -d talenthub -f candidates_seed.sql
--
-- 前置條件：
--     必須先完成 schema migration（建立 candidates / skills / candidate_* 等
--     資料表與枚舉、序列），本腳本才能執行。本檔僅負責 INSERT 資料，不建立
--     任何資料表結構。
--
-- 欄位名稱與枚舉值均依 docs/03-資料庫設計.md v1.0。
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1) 技能字典 skills：彙整 10 位人才全部技能去重，id 明確 1..74
--    重複匯入時以 name 唯一鍵 ON CONFLICT DO NOTHING。
-- -----------------------------------------------------------------------------
INSERT INTO skills (id, name) VALUES
  (1,  'Python'),
  (2,  'FastAPI'),
  (3,  'Django'),
  (4,  'PostgreSQL'),
  (5,  'Redis'),
  (6,  'Docker'),
  (7,  'Git'),
  (8,  'REST API'),
  (9,  'Vue.js'),
  (10, 'JavaScript'),
  (11, 'TypeScript'),
  (12, 'HTML5'),
  (13, 'CSS3'),
  (14, 'Nuxt.js'),
  (15, 'RWD'),
  (16, 'React'),
  (17, 'Node.js'),
  (18, 'MongoDB'),
  (19, 'MySQL'),
  (20, 'Express'),
  (21, 'AWS'),
  (22, 'SQL'),
  (23, 'Power BI'),
  (24, 'Tableau'),
  (25, 'Excel'),
  (26, 'Pandas'),
  (27, '統計分析'),
  (28, '資料視覺化'),
  (29, '專案管理'),
  (30, 'Scrum'),
  (31, 'JIRA'),
  (32, '需求分析'),
  (33, '風險管理'),
  (34, '團隊領導'),
  (35, 'Microsoft Project'),
  (36, '溝通協調'),
  (37, '招募甄選'),
  (38, '員工關係'),
  (39, '勞動法規'),
  (40, '教育訓練'),
  (41, '薪資計算'),
  (42, '面試技巧'),
  (43, '人事系統'),
  (44, '業務開發'),
  (45, '客戶關係管理'),
  (46, '商務談判'),
  (47, '報價管理'),
  (48, '市場分析'),
  (49, 'CRM'),
  (50, '簡報提案'),
  (51, '跨部門協調'),
  (52, '社群經營'),
  (53, '數位廣告'),
  (54, '內容行銷'),
  (55, 'Google Analytics'),
  (56, 'Facebook Ads'),
  (57, '文案撰寫'),
  (58, '活動企劃'),
  (59, 'Canva'),
  (60, '財務報表'),
  (61, '稅務申報'),
  (62, '總帳處理'),
  (63, '應收應付'),
  (64, '成本會計'),
  (65, '會計系統'),
  (66, '傳票處理'),
  (67, '品質管理'),
  (68, 'SPC'),
  (69, 'ISO 9001'),
  (70, '8D改善'),
  (71, 'FMEA'),
  (72, '檢驗規劃'),
  (73, '量測儀器'),
  (74, 'Minitab')
ON CONFLICT (name) DO NOTHING;

-- -----------------------------------------------------------------------------
-- 2) 人才主檔 candidates：id 明確 1..10
--    code            = 'T2026-00001'..'T2026-00010'
--    email_norm      = 小寫 email
--    phone_norm      = 去掉 '-' 的電話
--    source          = 依序輪替 p104 / p1111 / referral
--    status          = 'new'
--    consent_status  = 'platform'
--    retention_until = '2028-07-13'
--    summary         = 自傳
--    availability    = 依 docs/03 枚舉映射（面議→negotiable、一個月後→one_month、
--                      可立即上班→immediately、兩週後→two_weeks）
-- -----------------------------------------------------------------------------
INSERT INTO candidates (
  id, code, name, gender, birth_year, email, email_norm, phone, phone_norm,
  city, highest_education, total_years, current_title, current_company,
  expected_title, expected_cities, expected_salary_min, expected_salary_max,
  availability, source, status, consent_status, retention_until, summary,
  created_at, updated_at
) VALUES
  (1, 'T2026-00001', '林建宏', 'M', 1990, 'test01@example.com', 'test01@example.com',
   '0912-000-001', '0912000001', '台北', 'master', 10.0, '後端工程師(Python)', '頂尖雲端科技股份有限公司',
   '資深後端工程師', ARRAY['台北','新北'], 78000, 98000,
   'negotiable', 'p104', 'new', 'platform', '2028-07-13',
   '我是擁有十年經驗的後端工程師，專精 Python 生態系與雲端服務。過去主導電商平台的後端重構，透過容器化與快取機制大幅提升系統效能，也習慣以測試與程式碼審查維持團隊品質。個性沉穩、重視溝通，樂於將複雜需求拆解為可維護的架構。期望加入重視技術深度的團隊，持續在高流量系統領域精進。',
   now(), now()),
  (2, 'T2026-00002', '陳怡君', 'F', 1995, 'test02@example.com', 'test02@example.com',
   '0912-000-002', '0912000002', '新北', 'bachelor', 9.0, '前端工程師(Vue)', '亮點互動設計股份有限公司',
   '資深前端工程師', ARRAY['新北','台北'], 60000, 78000,
   'negotiable', 'p1111', 'new', 'platform', '2028-07-13',
   '我是專注於前端開發九年的工程師，熟悉 Vue 生態系與元件化開發，喜歡把設計稿轉化為流暢細膩的使用者介面。過去建立過跨專案共用元件庫，也導入 TypeScript 提升團隊協作品質。注重細節與使用體驗，能與設計及後端順暢溝通。期望在產品導向的團隊中，持續打磨前端工程與互動設計能力。',
   now(), now()),
  (3, 'T2026-00003', '張家豪', 'M', 1992, 'test03@example.com', 'test03@example.com',
   '0912-000-003', '0912000003', '台北', 'bachelor', 11.0, '全端工程師', '全方位軟體股份有限公司',
   '資深全端工程師', ARRAY['台北','新北'], 70000, 90000,
   'negotiable', 'referral', 'new', 'platform', '2028-07-13',
   '我是具備十一年經驗的全端工程師，能獨立完成產品從介面到伺服器的整體開發。長期投入 SaaS 產品，熟悉 React 與 Node.js，並具備雲端部署與系統監控經驗。喜歡從使用者需求出發思考架構，重視程式可維護性。期望加入具成長性的產品團隊，承擔更完整的技術規劃與跨端整合工作。',
   now(), now()),
  (4, 'T2026-00004', '黃詩涵', 'F', 1993, 'test04@example.com', 'test04@example.com',
   '0912-000-004', '0912000004', '新竹', 'master', 8.0, '資料分析師', '智數據科技股份有限公司',
   '資深資料分析師', ARRAY['新竹','台北'], 65000, 85000,
   'negotiable', 'p104', 'new', 'platform', '2028-07-13',
   '我是資料分析領域八年經驗的分析師，統計學碩士背景，擅長從龐雜資料中萃取商業洞察。熟悉 SQL、Python 與 BI 工具，曾為電商客戶建立預測模型與自動化報表，協助團隊做出數據驅動的決策。邏輯清晰、善於將分析結果轉譯為易懂的建議。期望在重視數據文化的企業持續深化分析與模型能力。',
   now(), now()),
  (5, 'T2026-00005', '王志明', 'M', 1985, 'test05@example.com', 'test05@example.com',
   '0912-000-005', '0912000005', '台北', 'master', 16.0, '軟體專案經理', '創新軟體整合股份有限公司',
   '專案經理／PM主管', ARRAY['台北'], 90000, 120000,
   'one_month', 'p1111', 'new', 'platform', '2028-07-13',
   '我是十六年資歷的軟體專案經理，從工程師一路成長至專案管理，熟悉軟體開發全生命週期。擅長跨部門協調與利害關係人溝通，曾主導多個大型系統導入專案並準時交付。持有 PMP 認證，善於在時程、預算與品質間取得平衡。期望帶領更具規模的專案團隊，將產業經驗轉化為穩定的交付成果。',
   now(), now()),
  (6, 'T2026-00006', '李佳蓉', 'F', 1996, 'test06@example.com', 'test06@example.com',
   '0912-000-006', '0912000006', '桃園', 'bachelor', 8.5, '人資專員', '群策人力資源股份有限公司',
   '人資專員／資深HR', ARRAY['桃園','新北'], 42000, 52000,
   'immediately', 'referral', 'new', 'platform', '2028-07-13',
   '我是八年多經驗的人資專員，橫跨製造業與人力資源業，熟悉招募到離職的完整流程。擅長經營招募管道並提升面試效率，也負責過教育訓練與員工關係處理。個性親切、細心可靠，重視同仁感受與制度落實。目前可立即上班，期望在重視人才發展的企業，承擔更完整的人資職能與專案。',
   now(), now()),
  (7, 'T2026-00007', '吳俊傑', 'M', 1991, 'test07@example.com', 'test07@example.com',
   '0912-000-007', '0912000007', '台中', 'bachelor', 12.0, 'B2B業務專員', '鴻遠貿易股份有限公司',
   '資深業務專員', ARRAY['台中','台北'], 42000, 58000,
   'negotiable', 'p104', 'new', 'platform', '2028-07-13',
   '我是十二年經驗的 B2B 業務，專精工業產品與企業客戶開發，熟悉從陌生開發、報價談判到售後服務的完整流程。過去在中部市場開發逾三十家新客戶並穩定達標，善於建立長期信任關係。個性積極、抗壓性高，樂於出差拜訪。期望加入具產品競爭力的企業，挑戰更大的業績目標與客戶版圖。',
   now(), now()),
  (8, 'T2026-00008', '許雅婷', 'F', 1997, 'test08@example.com', 'test08@example.com',
   '0912-000-008', '0912000008', '台北', 'bachelor', 6.0, '行銷企劃', '潮流行銷顧問股份有限公司',
   '資深行銷企劃', ARRAY['台北','新北'], 40000, 52000,
   'two_weeks', 'p1111', 'new', 'platform', '2028-07-13',
   '我是六年經驗的行銷企劃，專長社群經營與整合行銷，熟悉數位廣告投放與成效分析。曾操盤多檔品牌活動，透過內容與投放策略帶動流量與轉換成長。對趨勢敏銳、文案手感佳，能兼顧創意與數據。可於兩週後到職，期望在重視品牌成長的團隊，負責更完整的行銷策略規劃與執行。',
   now(), now()),
  (9, 'T2026-00009', '鄭美玲', 'F', 1988, 'test09@example.com', 'test09@example.com',
   '0912-000-009', '0912000009', '高雄', 'associate', 15.0, '會計專員', '誠信會計事務所',
   '資深會計／會計主任', ARRAY['高雄','台南'], 40000, 50000,
   'immediately', 'referral', 'new', 'platform', '2028-07-13',
   '我是十五年資歷的會計人員，橫跨製造業與會計事務所，熟悉帳務處理、結帳與各項稅務申報。持有會計事務乙級證照，對稅法與法規變動保持敏感，能獨立完成財報編製並提供稅務建議。個性嚴謹細心、責任感強。目前可立即上班，期望在穩定的企業擔任資深會計，承擔更完整的財稅職責。',
   now(), now()),
  (10, 'T2026-00010', '劉建良', 'M', 1990, 'test10@example.com', 'test10@example.com',
   '0912-000-010', '0912000010', '台南', 'bachelor', 12.0, '品保工程師', '精工品質檢測股份有限公司',
   '資深品保工程師', ARRAY['台南','高雄'], 50000, 62000,
   'negotiable', 'p104', 'new', 'platform', '2028-07-13',
   '我是十二年經驗的品保工程師，熟悉製造與電子產業的品質管理體系。專長 SPC 製程管制、8D 問題分析與 ISO 稽核，曾主導改善專案將客訴退貨率顯著降低。做事有條理、重視數據與根因分析，能與產線及供應商有效協作。期望在重視品質文化的企業，承擔更完整的品質系統規劃與改善工作。',
   now(), now());

-- -----------------------------------------------------------------------------
-- 3) 學歷 candidate_educations（一對多）
--    degree 沿用 highest_education 枚舉（碩士→master、學士→bachelor、專科→associate）
--    start_ym / end_ym 存 'yyyy-mm'
-- -----------------------------------------------------------------------------
INSERT INTO candidate_educations
  (candidate_id, school, major, degree, start_ym, end_ym, is_graduated, sort_order) VALUES
  (1,  '國立台北科技大學', '資訊工程',       'master',    '2013-09', '2015-06', true, 1),
  (1,  '淡江大學',         '資訊工程',       'bachelor',  '2009-09', '2013-06', true, 2),
  (2,  '輔仁大學',         '資訊管理',       'bachelor',  '2013-09', '2017-06', true, 1),
  (3,  '國立中央大學',     '資訊工程',       'bachelor',  '2011-09', '2015-06', true, 1),
  (4,  '國立清華大學',     '統計學',         'master',    '2016-09', '2018-06', true, 1),
  (4,  '國立中興大學',     '應用數學',       'bachelor',  '2012-09', '2016-06', true, 2),
  (5,  '國立政治大學',     '資訊管理',       'master',    '2008-09', '2010-06', true, 1),
  (5,  '逢甲大學',         '資訊工程',       'bachelor',  '2004-09', '2008-06', true, 2),
  (6,  '中原大學',         '人力資源管理',   'bachelor',  '2013-09', '2017-06', true, 1),
  (7,  '東海大學',         '國際企業',       'bachelor',  '2010-09', '2014-06', true, 1),
  (8,  '世新大學',         '廣告學',         'bachelor',  '2015-09', '2019-06', true, 1),
  (9,  '文藻外語專科學校', '會計',           'associate', '2006-09', '2008-06', true, 1),
  (10, '國立雲林科技大學', '工業工程與管理', 'bachelor',  '2010-09', '2014-06', true, 1);

-- -----------------------------------------------------------------------------
-- 4) 工作經歷 candidate_experiences（一對多）
--    在職者 end_ym = NULL（至今）
-- -----------------------------------------------------------------------------
INSERT INTO candidate_experiences
  (candidate_id, company, title, industry, start_ym, end_ym, description, sort_order) VALUES
  (1,  '頂尖雲端科技股份有限公司', '後端工程師(Python)', '資訊軟體業', '2020-03', NULL,
       '負責電商平台後端 API 設計與維運，使用 FastAPI 與 PostgreSQL，導入 Docker 容器化部署與 Redis 快取，將尖峰時段回應時間降低約四成，並帶領三人小組進行程式碼審查。', 1),
  (1,  '云智數位股份有限公司', '軟體工程師', '資訊軟體業', '2016-07', '2020-02',
       '開發企業內部管理系統與資料串接服務，負責訂單模組與第三方金流整合，撰寫單元測試並維護 CI/CD 流程。', 2),
  (2,  '亮點互動設計股份有限公司', '前端工程師(Vue)', '資訊軟體業', '2021-05', NULL,
       '以 Vue.js 與 Nuxt 開發企業官網與後台管理介面，建立共用元件庫並導入 TypeScript，改善跨專案開發效率，同時負責與設計師協作落實 RWD 響應式版面。', 1),
  (2,  '網際數位有限公司', '網頁前端工程師', '資訊軟體業', '2017-08', '2021-04',
       '負責活動網頁與電商前台切版，使用 Vue.js 與 JavaScript 串接後端 API，並優化網頁載入速度與 SEO。', 2),
  (3,  '全方位軟體股份有限公司', '全端工程師', '資訊軟體業', '2019-02', NULL,
       '獨立負責 SaaS 產品從前端到後端的開發，前端使用 React、後端以 Node.js 與 MongoDB 建構，並規劃 AWS 部署架構與監控，支援多家企業客戶穩定上線。', 1),
  (3,  '銳思科技有限公司', '軟體工程師', '資訊軟體業', '2015-06', '2019-01',
       '參與內容管理系統開發，負責前後端功能實作與資料庫設計，並協助新進同仁熟悉專案架構。', 2),
  (4,  '智數據科技股份有限公司', '資料分析師', '資訊軟體業', '2021-09', NULL,
       '負責電商與零售客戶的營運數據分析，建立 SQL 資料管線與 Power BI 儀表板，運用 Python 進行客群分群與銷售預測，協助行銷團隊優化投放策略。', 1),
  (4,  '宏觀顧問有限公司', '商業分析師', '顧問業', '2018-07', '2021-08',
       '協助客戶進行市場調查與資料視覺化報告，整理問卷與交易資料並提出營運建議。', 2),
  (5,  '創新軟體整合股份有限公司', '軟體專案經理', '資訊軟體業', '2017-04', NULL,
       '帶領跨部門團隊執行金融與零售產業的系統導入專案，管理時程、預算與利害關係人溝通，同時導入敏捷開發流程，成功交付多個逾千萬規模的專案。', 1),
  (5,  '泰鼎資訊股份有限公司', '專案副理', '資訊軟體業', '2013-01', '2017-03',
       '負責 ERP 客製化專案的需求訪談與進度控管，協調開發與客戶端，確保專案準時上線。', 2),
  (5,  '華鋒科技有限公司', '系統工程師', '資訊軟體業', '2010-08', '2012-12',
       '負責系統建置與客戶技術支援，累積需求分析與問題排解經驗。', 3),
  (6,  '群策人力資源股份有限公司', '人資專員', '人力資源業', '2020-03', '2025-12',
       '負責招募甄選與到離職作業，經營多元招募管道並優化面試流程，同時處理員工關係與教育訓練規劃，年度招募達成率維持九成以上。', 1),
  (6,  '佳緣企業有限公司', '人資助理', '製造業', '2017-06', '2020-02',
       '協助出勤與薪資計算、勞健保申報及新人報到作業，維護人事資料系統。', 2),
  (7,  '鴻遠貿易股份有限公司', 'B2B業務專員', '批發貿易業', '2018-09', NULL,
       '負責工業零組件的企業客戶開發與維護，涵蓋報價、合約洽談與交期協調，開發新客戶超過三十家，連續三年達成業績目標並拓展中部市場。', 1),
  (7,  '建達實業有限公司', '業務代表', '製造業', '2014-07', '2018-08',
       '負責既有客戶維護與訂單管理，協助處理客訴與售後服務，建立穩定的客戶關係。', 2),
  (8,  '潮流行銷顧問股份有限公司', '行銷企劃', '廣告行銷業', '2021-02', '2026-03',
       '負責品牌社群經營與整合行銷活動規劃，操作 Facebook 與 Instagram 廣告投放，並以 Google Analytics 追蹤成效，帶動客戶官網流量成長逾五成。', 1),
  (8,  '悅讀文創有限公司', '行銷助理', '文創業', '2020-01', '2021-01',
       '協助活動宣傳素材製作、社群貼文撰寫與媒體聯繫，支援線上線下活動執行。', 2),
  (9,  '誠信會計事務所', '會計專員', '會計服務業', '2016-05', '2026-02',
       '負責多家中小企業帳務處理與結帳、營業稅與營所稅申報，並協助財務報表編製與稅務諮詢，熟悉稅法變動並確保客戶申報準時無誤。', 1),
  (9,  '南方紡織有限公司', '會計助理', '製造業', '2010-09', '2016-04',
       '處理傳票登錄、應收應付帳款與零用金管理，協助月結與盤點作業。', 2),
  (10, '精工品質檢測股份有限公司', '品保工程師', '製造業', '2018-03', NULL,
       '負責產線品質管理與客訴分析，導入 SPC 統計製程管制與 8D 改善流程，主導 ISO 9001 內部稽核，將客訴退貨率降低約三成。', 1),
  (10, '立信電子有限公司', '品管員', '電子業', '2014-07', '2018-02',
       '執行進料與出貨檢驗，撰寫檢驗報告並追蹤不良品處理，協助供應商品質改善。', 2);

-- -----------------------------------------------------------------------------
-- 5) 技能關聯 candidate_skills
--    skill_id 以 (SELECT id FROM skills WHERE name='...') 帶入，source='manual'
-- -----------------------------------------------------------------------------
INSERT INTO candidate_skills (candidate_id, skill_id, source) VALUES
  (1, (SELECT id FROM skills WHERE name='Python'),     'manual'),
  (1, (SELECT id FROM skills WHERE name='FastAPI'),    'manual'),
  (1, (SELECT id FROM skills WHERE name='Django'),     'manual'),
  (1, (SELECT id FROM skills WHERE name='PostgreSQL'), 'manual'),
  (1, (SELECT id FROM skills WHERE name='Redis'),      'manual'),
  (1, (SELECT id FROM skills WHERE name='Docker'),     'manual'),
  (1, (SELECT id FROM skills WHERE name='Git'),        'manual'),
  (1, (SELECT id FROM skills WHERE name='REST API'),   'manual'),
  (2, (SELECT id FROM skills WHERE name='Vue.js'),     'manual'),
  (2, (SELECT id FROM skills WHERE name='JavaScript'), 'manual'),
  (2, (SELECT id FROM skills WHERE name='TypeScript'), 'manual'),
  (2, (SELECT id FROM skills WHERE name='HTML5'),      'manual'),
  (2, (SELECT id FROM skills WHERE name='CSS3'),       'manual'),
  (2, (SELECT id FROM skills WHERE name='Nuxt.js'),    'manual'),
  (2, (SELECT id FROM skills WHERE name='Git'),        'manual'),
  (2, (SELECT id FROM skills WHERE name='RWD'),        'manual'),
  (3, (SELECT id FROM skills WHERE name='React'),      'manual'),
  (3, (SELECT id FROM skills WHERE name='Node.js'),    'manual'),
  (3, (SELECT id FROM skills WHERE name='JavaScript'), 'manual'),
  (3, (SELECT id FROM skills WHERE name='MongoDB'),    'manual'),
  (3, (SELECT id FROM skills WHERE name='MySQL'),      'manual'),
  (3, (SELECT id FROM skills WHERE name='Express'),    'manual'),
  (3, (SELECT id FROM skills WHERE name='AWS'),        'manual'),
  (3, (SELECT id FROM skills WHERE name='Git'),        'manual'),
  (3, (SELECT id FROM skills WHERE name='Docker'),     'manual'),
  (4, (SELECT id FROM skills WHERE name='Python'),     'manual'),
  (4, (SELECT id FROM skills WHERE name='SQL'),        'manual'),
  (4, (SELECT id FROM skills WHERE name='Power BI'),   'manual'),
  (4, (SELECT id FROM skills WHERE name='Tableau'),    'manual'),
  (4, (SELECT id FROM skills WHERE name='Excel'),      'manual'),
  (4, (SELECT id FROM skills WHERE name='Pandas'),     'manual'),
  (4, (SELECT id FROM skills WHERE name='統計分析'),   'manual'),
  (4, (SELECT id FROM skills WHERE name='資料視覺化'), 'manual'),
  (5, (SELECT id FROM skills WHERE name='專案管理'),          'manual'),
  (5, (SELECT id FROM skills WHERE name='Scrum'),            'manual'),
  (5, (SELECT id FROM skills WHERE name='JIRA'),             'manual'),
  (5, (SELECT id FROM skills WHERE name='需求分析'),         'manual'),
  (5, (SELECT id FROM skills WHERE name='風險管理'),         'manual'),
  (5, (SELECT id FROM skills WHERE name='團隊領導'),         'manual'),
  (5, (SELECT id FROM skills WHERE name='Microsoft Project'),'manual'),
  (5, (SELECT id FROM skills WHERE name='溝通協調'),         'manual'),
  (6, (SELECT id FROM skills WHERE name='招募甄選'),   'manual'),
  (6, (SELECT id FROM skills WHERE name='員工關係'),   'manual'),
  (6, (SELECT id FROM skills WHERE name='勞動法規'),   'manual'),
  (6, (SELECT id FROM skills WHERE name='教育訓練'),   'manual'),
  (6, (SELECT id FROM skills WHERE name='薪資計算'),   'manual'),
  (6, (SELECT id FROM skills WHERE name='面試技巧'),   'manual'),
  (6, (SELECT id FROM skills WHERE name='Excel'),      'manual'),
  (6, (SELECT id FROM skills WHERE name='人事系統'),   'manual'),
  (7, (SELECT id FROM skills WHERE name='業務開發'),     'manual'),
  (7, (SELECT id FROM skills WHERE name='客戶關係管理'), 'manual'),
  (7, (SELECT id FROM skills WHERE name='商務談判'),     'manual'),
  (7, (SELECT id FROM skills WHERE name='報價管理'),     'manual'),
  (7, (SELECT id FROM skills WHERE name='市場分析'),     'manual'),
  (7, (SELECT id FROM skills WHERE name='CRM'),          'manual'),
  (7, (SELECT id FROM skills WHERE name='簡報提案'),     'manual'),
  (7, (SELECT id FROM skills WHERE name='跨部門協調'),   'manual'),
  (8, (SELECT id FROM skills WHERE name='社群經營'),        'manual'),
  (8, (SELECT id FROM skills WHERE name='數位廣告'),        'manual'),
  (8, (SELECT id FROM skills WHERE name='內容行銷'),        'manual'),
  (8, (SELECT id FROM skills WHERE name='Google Analytics'),'manual'),
  (8, (SELECT id FROM skills WHERE name='Facebook Ads'),    'manual'),
  (8, (SELECT id FROM skills WHERE name='文案撰寫'),        'manual'),
  (8, (SELECT id FROM skills WHERE name='活動企劃'),        'manual'),
  (8, (SELECT id FROM skills WHERE name='Canva'),           'manual'),
  (9, (SELECT id FROM skills WHERE name='財務報表'),   'manual'),
  (9, (SELECT id FROM skills WHERE name='稅務申報'),   'manual'),
  (9, (SELECT id FROM skills WHERE name='總帳處理'),   'manual'),
  (9, (SELECT id FROM skills WHERE name='應收應付'),   'manual'),
  (9, (SELECT id FROM skills WHERE name='成本會計'),   'manual'),
  (9, (SELECT id FROM skills WHERE name='Excel'),      'manual'),
  (9, (SELECT id FROM skills WHERE name='會計系統'),   'manual'),
  (9, (SELECT id FROM skills WHERE name='傳票處理'),   'manual'),
  (10,(SELECT id FROM skills WHERE name='品質管理'),   'manual'),
  (10,(SELECT id FROM skills WHERE name='SPC'),        'manual'),
  (10,(SELECT id FROM skills WHERE name='ISO 9001'),   'manual'),
  (10,(SELECT id FROM skills WHERE name='8D改善'),     'manual'),
  (10,(SELECT id FROM skills WHERE name='FMEA'),       'manual'),
  (10,(SELECT id FROM skills WHERE name='檢驗規劃'),   'manual'),
  (10,(SELECT id FROM skills WHERE name='量測儀器'),   'manual'),
  (10,(SELECT id FROM skills WHERE name='Minitab'),    'manual');

-- -----------------------------------------------------------------------------
-- 6) 語言 candidate_languages
--    listening / speaking / reading / writing 使用（略懂 / 中等 / 精通）
-- -----------------------------------------------------------------------------
INSERT INTO candidate_languages
  (candidate_id, language, listening, speaking, reading, writing) VALUES
  (1,  '英語', '中等', '中等', '中等', '中等'),
  (1,  '台語', '精通', '精通', '精通', '精通'),
  (2,  '英語', '中等', '中等', '中等', '中等'),
  (2,  '台語', '中等', '中等', '中等', '中等'),
  (3,  '英語', '中等', '中等', '中等', '中等'),
  (3,  '台語', '精通', '精通', '精通', '精通'),
  (4,  '英語', '精通', '精通', '精通', '精通'),
  (4,  '台語', '中等', '中等', '中等', '中等'),
  (5,  '英語', '精通', '精通', '精通', '精通'),
  (5,  '台語', '精通', '精通', '精通', '精通'),
  (6,  '英語', '中等', '中等', '中等', '中等'),
  (6,  '台語', '中等', '中等', '中等', '中等'),
  (7,  '英語', '中等', '中等', '中等', '中等'),
  (7,  '台語', '精通', '精通', '精通', '精通'),
  (8,  '英語', '中等', '中等', '中等', '中等'),
  (8,  '台語', '中等', '中等', '中等', '中等'),
  (9,  '台語', '精通', '精通', '精通', '精通'),
  (9,  '英語', '略懂', '略懂', '略懂', '略懂'),
  (10, '英語', '中等', '中等', '中等', '中等'),
  (10, '台語', '精通', '精通', '精通', '精通');

-- -----------------------------------------------------------------------------
-- 7) 證照 candidate_certifications
-- -----------------------------------------------------------------------------
INSERT INTO candidate_certifications (candidate_id, name) VALUES
  (1,  'AWS Certified Developer'),
  (4,  'Google Data Analytics'),
  (5,  'PMP'),
  (5,  'Scrum Master (CSM)'),
  (6,  '勞工行政與勞動法規結業'),
  (8,  'Google Analytics 個人認證'),
  (9,  '會計事務-丙級技術士'),
  (9,  '會計事務-乙級技術士'),
  (10, 'ISO 9001 內部稽核員');

-- -----------------------------------------------------------------------------
-- 8) 修正序列（id sequence），避免後續自動產生的 id 與明確指定值衝突
-- -----------------------------------------------------------------------------
SELECT setval(pg_get_serial_sequence('candidates', 'id'), 10, true);
SELECT setval(pg_get_serial_sequence('skills', 'id'), 74, true);

COMMIT;
