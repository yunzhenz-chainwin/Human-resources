import { expect, test, type Page } from '@playwright/test'

const backendApi = 'http://127.0.0.1:8018/api/v1'

const candidateNameFor = (retry: number) => `端對端測試人才 R${retry}`
const noResumeNameFor = (retry: number) => `無履歷測試人才 R${retry}`
const resumeNameFor = (retry: number) => `talenthub-e2e-resume-r${retry}.pdf`
const interviewCandidateNameFor = (retry: number) => `E2E 面試流程人才 R${retry}`
const departmentJobNameFor = (retry: number) => `E2E 部門雲端工程師 R${retry}`

// The upload validator requires a PDF signature. The parser may mark this tiny
// synthetic document for review; submitted form fields remain the source of truth.
const minimalPdf = Buffer.from('%PDF-1.4\n% synthetic E2E resume - no personal data\n%%EOF\n')

async function openUnifiedInterviews(page: Page) {
  await page.getByTestId('nav-matching').click()
  const workspace = page.getByTestId('unified-talent-workspace')
  await expect(workspace).toBeVisible()
  await expect(workspace.getByTestId('unified-workspace-mode-matching')).toHaveAttribute(
    'aria-selected',
    'true',
  )
  await workspace.getByTestId('unified-workspace-mode-interviews').click()
  await expect(workspace.getByTestId('unified-workspace-mode-interviews')).toHaveAttribute(
    'aria-selected',
    'true',
  )
  await expect(page.getByTestId('interview-management')).toBeVisible()
}

async function expandInterviewApplication(page: Page, applicationId: number) {
  const card = page.getByTestId(`interview-application-${applicationId}`)
  await expect(card).toBeVisible()
  const toggle = card.getByTestId(`interview-row-toggle-${applicationId}`)
  if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click()
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  return card
}

test.describe.serial('public submission to HR review', () => {
  test('talent can join with selections and no resume file', async ({ page }, testInfo) => {
    await page.goto('http://127.0.0.1:4174')

    await expect(page.getByRole('heading', { name: '加入人才庫' })).toBeVisible()
    await expect(page.getByTestId('career-journey')).toHaveCount(0)
    await page.getByLabel('姓名 *').fill(noResumeNameFor(testInfo.retry))
    await page.getByLabel('手機（與 Email 擇一）').fill('0912-000-123')
    await page.getByLabel('希望工作地點').selectOption('遠端工作')
    await page.getByLabel('職務類別').selectOption('產品／專案管理')
    await page.getByLabel('工作年資').selectOption({ label: '3–5 年' })
    await page.getByLabel('主要專長').selectOption('專案管理')
    await page.getByRole('checkbox').check()
    await page.getByRole('button', { name: '加入人才庫', exact: true }).last().click()
    await expect(page.getByRole('heading', { name: '已成功加入人才庫' })).toBeVisible()
    await expect(page.getByText(/參考編號：\d+/)).toBeVisible()
  })

  test('public career page submits a resume without authentication', async ({ page }, testInfo) => {
    const candidateName = candidateNameFor(testInfo.retry)
    const resumeName = resumeNameFor(testInfo.retry)
    await page.goto('http://127.0.0.1:4174')
    await expect(page.getByRole('heading', { name: '加入人才庫' })).toBeVisible()
    await expect(page.getByTestId('career-journey')).toHaveCount(0)
    await expect(page.getByText('登入 HR 工作台')).toHaveCount(0)

    await page.getByLabel('姓名 *').fill(candidateName)
    await page.getByLabel('Email（與手機擇一）').fill(`e2e-candidate-r${testInfo.retry}@example.test`)
    await page.getByLabel('希望工作地點').selectOption('台北市')
    await page.getByLabel('職務類別').selectOption('軟體／資訊')
    await page.getByLabel('主要專長').selectOption('軟體開發')
    await page.locator('input[type="file"]').setInputFiles({
      name: resumeName,
      mimeType: 'application/pdf',
      buffer: minimalPdf,
    })
    await page.getByRole('checkbox').check()
    await page.getByRole('button', { name: '加入人才庫', exact: true }).last().click()

    await expect(page.getByRole('heading', { name: '已成功加入人才庫' })).toBeVisible()
    await expect(page.getByText(/參考編號：\d+/)).toBeVisible()
  })

  test('HR requires login, admin loads core pages and confirms submitted talent', async ({ page }, testInfo) => {
    test.setTimeout(90_000)
    const candidateName = candidateNameFor(testInfo.retry)
    const resumeName = resumeNameFor(testInfo.retry)
    await page.goto('http://127.0.0.1:4173')
    await expect(page.getByRole('heading', { name: '登入 HR 工作台' })).toBeVisible()
    await page.getByLabel('帳號或 Email').fill('e2e-admin')
    await page.getByLabel('密碼').fill('E2E-Admin-Password-123!')
    await page.getByRole('button', { name: '登入工作台' }).click()

    await page.setViewportSize({ width: 1280, height: 620 })
    const sidebarLayout = await page.locator('.sidebar').evaluate((sidebar) => {
      const nav = sidebar.querySelector('nav')
      const lastItem = sidebar.querySelector('.nav-item:last-of-type')
      const footer = sidebar.querySelector('.sidebar-footer')
      return {
        sidebarClientHeight: sidebar.clientHeight,
        sidebarScrollHeight: sidebar.scrollHeight,
        navClientHeight: nav?.clientHeight ?? 0,
        navScrollHeight: nav?.scrollHeight ?? 0,
        lastItemBottom: lastItem?.getBoundingClientRect().bottom ?? 0,
        footerTop: footer?.getBoundingClientRect().top ?? 0,
      }
    })
    expect(sidebarLayout.sidebarScrollHeight).toBeLessThanOrEqual(sidebarLayout.sidebarClientHeight + 1)
    expect(sidebarLayout.navScrollHeight).toBeLessThanOrEqual(sidebarLayout.navClientHeight + 1)
    expect(sidebarLayout.lastItemBottom).toBeLessThanOrEqual(sidebarLayout.footerTop + 1)
    await page.setViewportSize({ width: 1280, height: 720 })

    const intakeRoute = page.getByTestId('intake-route-guide')
    await expect(intakeRoute).toBeVisible()
    await expect(intakeRoute.locator('[data-testid^="intake-route-stop-"]')).toHaveCount(4)
    // 滑過路標可先預覽該關說明（aria-current 標記 + 右側說明卡）
    await page.getByTestId('intake-route-stop-3').hover()
    await expect(page.getByTestId('intake-route-stop-3')).toHaveAttribute('aria-current', 'step')
    await expect(intakeRoute.getByText('指定應徵部門與職缺', { exact: true })).toBeVisible()
    await expect(page.locator('.intake-workspace')).toHaveCount(0)
    // 點擊路標會直接前往該關（人才庫），不需再點右側按鈕
    await page.getByTestId('intake-route-stop-3').click()
    await expect(page.getByRole('button', { name: '＋ 手動新增人才' })).toBeVisible()
    await page.getByRole('button', { name: '工作總覽' }).click()
    await expect(intakeRoute).toBeVisible()
    for (const label of ['人才評估與面試', '招募分析', '帳號與權限']) {
      await expect(page.getByRole('button', { name: label })).toBeVisible()
    }
    await expect(page.getByTestId('nav-matching')).toBeVisible()
    await expect(page.getByTestId('nav-interviews')).toHaveCount(0)

    await page.getByRole('button', { name: '職缺管理' }).click()
    await page.getByRole('button', { name: '＋ 建立職缺' }).click()
    const jobDialog = page.getByRole('dialog', { name: '建立職缺' })
    await jobDialog.getByLabel('職缺名稱 *').fill('E2E 去識別化分析職缺')
    await jobDialog.getByLabel('職務說明 *').fill('負責 Python API、SQL 與跨部門協作。')
    await jobDialog.getByLabel('技能（逗號分隔）').fill('Python, SQL, API')
    await jobDialog.getByLabel('流程狀態').selectOption('submitted')
    const jobCreated = page.waitForResponse(response => (
      response.url().endsWith('/api/v1/requisitions')
      && response.request().method() === 'POST'
    ))
    await jobDialog.getByRole('button', { name: '儲存至資料庫' }).click()
    expect((await jobCreated).status()).toBe(201)
    await expect(page.getByText('職缺已建立')).toBeVisible()
    const createdJobCard = page.locator('.job-card').filter({ hasText: 'E2E 去識別化分析職缺' })
    const jobApproved = page.waitForResponse(response => (
      /\/api\/v1\/requisitions\/\d+\/approve$/.test(response.url())
      && response.request().method() === 'POST'
    ))
    await createdJobCard.getByRole('button', { name: '核准職缺' }).click()
    expect((await jobApproved).status()).toBe(200)
    await expect(page.getByText('職缺已核准並可供前台讀取')).toBeVisible()

    await page.getByTestId('nav-resumes').click()
    await expect(page.getByTestId('resume-center-flow')).toBeVisible()
    await expect(page.locator('[data-testid^="resume-center-step-"]')).toHaveCount(3)
    const resumeUploadInput = page.getByTestId('resume-upload-input')
    await resumeUploadInput.setInputFiles({
      name: 'unsupported-e2e.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('not a supported resume'),
    })
    await expect(page.getByTestId('resume-upload-validation-error')).toContainText('僅支援 PDF、DOC、DOCX')
    await resumeUploadInput.setInputFiles({
      name: 'removable-e2e.pdf',
      mimeType: 'application/pdf',
      buffer: minimalPdf,
    })
    await expect(page.getByTestId('resume-upload-filename-0')).toHaveText('removable-e2e.pdf')
    await page.getByTestId('resume-upload-remove-0').click()
    await expect(page.getByTestId('resume-upload-progress')).toHaveCount(0)
    await page.getByRole('button', { name: new RegExp(resumeName) }).click()
    await expect(page.getByLabel('姓名 *')).toHaveValue(candidateName)
    // A synthetic PDF has no verifiable platform signature, so HR must explicitly
    // confirm the detected source before the record can enter the talent pool.
    await page.getByRole('button', { name: '一般／自製履歷', exact: true }).click()
    await page.getByRole('button', { name: '確認並寫入人才庫' }).click()
    await expect(page.getByText(/已建立人才|已更新人才/)).toBeVisible()
    await expect(page.getByTestId('resume-confirmed-summary')).toContainText('本次已入庫 1 份')
    await expect(page.getByRole('button', { name: new RegExp(resumeName) })).toHaveCount(0)

    await page.getByRole('button', { name: '人才庫' }).click()
    await expect(page.getByRole('button', { name: new RegExp(candidateName) })).toBeVisible()
    await page.getByRole('button', { name: new RegExp(candidateName) }).click()
    await expect(page.getByTestId('candidate-detail-panel-profile')).toBeVisible()
    await page.getByTestId('candidate-detail-tab-documents').click()
    await expect(page.getByTestId('candidate-resumes')).toContainText(resumeName)
    const previewLoaded = page.waitForResponse(response => (
      response.url().includes('/api/v1/resumes/')
      && response.url().endsWith('/preview')
      && response.request().method() === 'GET'
    ))
    await page.getByRole('button', { name: '先預覽原始履歷' }).click()
    const previewResponse = await previewLoaded
    expect(previewResponse.status()).toBe(200)
    expect(previewResponse.headers()['content-type']).toContain('application/pdf')
    const resumePreviewDialog = page.getByTestId('candidate-analysis-preview')
    await expect(resumePreviewDialog).toBeVisible()
    await expect(resumePreviewDialog.locator('iframe')).toHaveAttribute('src', /^blob:/)
    await resumePreviewDialog.getByRole('button', { name: '關閉預覽' }).click()
    await expect(resumePreviewDialog).toHaveCount(0)

    const deidentificationSaved = page.waitForResponse(response => (
      /\/api\/v1\/resumes\/\d+\/deidentifications$/.test(response.url())
      && response.request().method() === 'POST'
    ))
    const deidentificationChooser = page.waitForEvent('filechooser')
    await page.getByTestId('deidentification-primary-upload').click()
    await (await deidentificationChooser).setFiles({
      name: 'deidentified-e2e.pdf',
      mimeType: 'application/pdf',
      buffer: minimalPdf,
    })
    const deidentificationResponse = await deidentificationSaved
    expect(deidentificationResponse.status()).toBe(201)
    const savedDocument = await deidentificationResponse.json() as { id: number; version: number }
    await expect(page.getByTestId('deidentification-notice')).toContainText('已上傳並保存')
    await expect(page.getByTestId('analysis-current-document')).toContainText(`去識別化履歷 v${savedDocument.version}`)

    const deidentifiedPreviewLoaded = page.waitForResponse(response => (
      response.url().endsWith(`/api/v1/deidentified-resumes/${savedDocument.id}/preview`)
      && response.request().method() === 'GET'
    ))
    await page.getByTestId('deidentification-primary-preview').click()
    expect((await deidentifiedPreviewLoaded).status()).toBe(200)
    await expect(page.getByTestId('candidate-analysis-preview').locator('iframe')).toHaveAttribute('src', /^blob:/)
    await page.getByTestId('candidate-analysis-preview').getByRole('button', { name: '關閉預覽' }).click()

    const deidentificationApproved = page.waitForResponse(response => (
      response.url().endsWith(`/api/v1/deidentified-resumes/${savedDocument.id}/approve`)
      && response.request().method() === 'POST'
    ))
    await page.getByTestId('deidentification-primary-approve').click()
    expect((await deidentificationApproved).status()).toBe(200)
    await expect(page.getByTestId('analysis-ready-banner')).toBeVisible()

    const recommendedAnalysisCompleted = page.waitForResponse(response => (
      response.url().endsWith(`/api/v1/deidentified-resumes/${savedDocument.id}/analyses/recommended-roles`)
      && response.request().method() === 'POST'
    ))
    await page.getByTestId('recommend-roles-button').click()
    expect((await recommendedAnalysisCompleted).status()).toBe(200)
    await expect(page.getByTestId('recommended-role-results')).toBeVisible()

    const roleSelect = page.getByTestId('role-match-job-select')
    const roleOption = await roleSelect.locator('option').nth(1).getAttribute('value')
    expect(roleOption).toBeTruthy()
    await roleSelect.selectOption(roleOption!)
    const roleMatchCompleted = page.waitForResponse(response => (
      response.url().endsWith(`/api/v1/deidentified-resumes/${savedDocument.id}/analyses/role-match`)
      && response.request().method() === 'POST'
    ))
    await page.getByTestId('role-match-button').click()
    expect((await roleMatchCompleted).status()).toBe(200)
    await expect(page.getByTestId('role-match-result')).toBeVisible()

    await page.getByRole('button', { name: '關閉人才詳情' }).click()
    await page.getByRole('button', { name: new RegExp(candidateName) }).click()
    await page.getByTestId('candidate-detail-tab-documents').click()
    await expect(page.getByTestId('analysis-ready-banner')).toContainText(`v${savedDocument.version}`)
    await expect(page.getByTestId('recommended-role-results')).toHaveCount(0)
    const persistedPreviewLoaded = page.waitForResponse(response => (
      response.url().endsWith(`/api/v1/deidentified-resumes/${savedDocument.id}/preview`)
      && response.request().method() === 'GET'
    ))
    await page.getByTestId('analysis-ready-banner').getByRole('button', { name: '再次預覽檔案' }).click()
    expect((await persistedPreviewLoaded).status()).toBe(200)
    await expect(page.getByTestId('candidate-analysis-preview').locator('iframe')).toHaveAttribute('src', /^blob:/)
    await page.getByTestId('candidate-analysis-preview').getByRole('button', { name: '關閉預覽' }).click()
    await page.getByRole('button', { name: '關閉人才詳情' }).click()

    await page.getByRole('button', { name: '帳號與權限' }).click()
    await expect(page.getByRole('heading', { name: '帳號與權限' })).toBeVisible()
    await expect(page.getByText('e2e-admin@example.test')).toBeVisible()
    const salesAccount = page.locator('tr').filter({ hasText: 'sales' })
    await expect(salesAccount).toBeVisible()
    page.once('dialog', dialog => dialog.accept())
    const passwordReset = page.waitForResponse(response =>
      response.url().includes('/api/v1/admin/users/')
      && response.url().endsWith('/reset-password')
      && response.request().method() === 'POST',
    )
    await salesAccount.getByRole('button', { name: '產生一次性臨時密碼' }).click()
    expect((await passwordReset).status()).toBe(200)
    const temporaryPassword = page.getByTestId('temporary-password-value')
    await expect(page.getByTestId('temporary-password-dialog')).toBeVisible()
    await expect(temporaryPassword).toHaveValue(/^(?=.{24}$).+$/)
    await page.getByTestId('close-temp-password').click()
    await expect(page.getByTestId('temporary-password-dialog')).toHaveCount(0)
  })

  test('IT can temporarily reveal and re-mask candidate PII with a reason', async ({ page }) => {
    await page.goto('http://127.0.0.1:4173')
    await page.getByLabel('帳號或 Email').fill('e2e-admin')
    await page.getByLabel('密碼').fill('E2E-Admin-Password-123!')
    await page.getByRole('button', { name: '登入工作台' }).click()
    await page.getByRole('button', { name: '帳號與權限' }).click()
    await page.getByRole('tab', { name: '資料表維護' }).click()
    await page.getByRole('button', { name: /人才主檔/ }).click()

    await page.getByRole('button', { name: '顯示個資' }).click()
    await page.getByLabel('查閱原因 *').fill('E2E 驗證 HR 人才同步問題')
    await page.getByRole('button', { name: '確認並顯示' }).click()
    await expect(page.getByRole('button', { name: '重新遮罩' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'name', exact: true })).toBeVisible()

    await page.getByRole('button', { name: '重新遮罩' }).click()
    await expect(page.getByRole('button', { name: '顯示個資' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'name', exact: true })).toHaveCount(0)
  })

  test('HR creates a real application and only its department manager can manage the interview', async ({ page, request }, testInfo) => {
    test.setTimeout(90_000)
    const interviewCandidateName = interviewCandidateNameFor(testInfo.retry)
    const adminLogin = await request.post(`${backendApi}/auth/login`, {
      data: { username: 'e2e-admin', password: 'E2E-Admin-Password-123!' },
    })
    expect(adminLogin.ok()).toBeTruthy()
    const adminToken = (await adminLogin.json()).access_token as string
    const createHr = await request.post(`${backendApi}/admin/users`, {
      headers: { Authorization: `Bearer ${adminToken}` },
      data: {
        username: 'e2e-hr',
        email: 'e2e-hr@example.test',
        password: 'E2E-HR-Password-123!',
        display_name: 'E2E HR',
        role: 'hr',
        department_id: null,
      },
    })
    expect([201, 409]).toContain(createHr.status())
    const hrApiLogin = await request.post(`${backendApi}/auth/login`, {
      data: { username: 'e2e-hr', password: 'E2E-HR-Password-123!' },
    })
    expect(hrApiLogin.ok()).toBeTruthy()
    const hrToken = (await hrApiLogin.json()).access_token as string

    await page.goto('http://127.0.0.1:4173')
    await page.getByLabel('帳號或 Email').fill('e2e-hr')
    await page.getByLabel('密碼').fill('E2E-HR-Password-123!')
    await page.getByRole('button', { name: '登入工作台' }).click()
    await expect(page.getByTestId('intake-route-guide')).toBeVisible()

    await page.getByTestId('nav-candidates').click()
    await page.getByRole('button', { name: /手動新增人才/ }).click()
    await expect(page.getByRole('heading', { name: '新增人才' })).toBeVisible()
    await page.getByLabel('姓名 *').fill(interviewCandidateName)
    await page.getByLabel('Email').fill(`e2e-interview-candidate-r${testInfo.retry}@example.test`)
    await page.getByLabel('目前職稱').fill('平台工程師')
    const departmentSelect = page.getByTestId('candidate-department-select')
    const jobSelect = page.getByTestId('candidate-job-select')
    await expect(jobSelect).toBeDisabled()
    await departmentSelect.selectOption({ label: '資訊技術部' })
    await expect(jobSelect).toBeEnabled()
    const targetJobId = await jobSelect.locator('option', { hasText: '資深後端工程師' }).getAttribute('value')
    expect(targetJobId).toBeTruthy()
    await jobSelect.selectOption(targetJobId!)
    const applicationCreated = page.waitForResponse(response =>
      response.url().endsWith('/api/v1/applications')
      && response.request().method() === 'POST',
    )
    await page.getByRole('button', { name: '儲存至資料庫' }).click()
    const createApplicationResponse = await applicationCreated
    expect(createApplicationResponse.status()).toBe(201)
    const application = await createApplicationResponse.json() as {
      id: number
      candidate: { id: number; name: string }
      requisition: { title: string; department_name: string | null }
    }
    expect(application.candidate.name).toBe(interviewCandidateName)
    expect(application.requisition.title).toBe('資深後端工程師')
    expect(application.requisition.department_name).toBe('資訊技術部')

    const legacyHrQuestion = 'LEGACY HR QUESTION MUST NOT HIDE THE GENERATED PLAN'
    const legacyRecordCreated = await request.post(
      `${backendApi}/applications/${application.id}/interview-records`,
      {
        headers: { Authorization: `Bearer ${hrToken}` },
        data: {
          stage: 'hr',
          interviewed_at: '2026-08-20T06:30:00.000Z',
          duration_minutes: 45,
          mode: 'video',
          status: 'in_progress',
          questions: Array.from({ length: 5 }, (_, index) => ({
            question: index === 0 ? legacyHrQuestion : `LEGACY HR QUESTION ${index + 1}`,
            response: '',
            rating: null,
            notes: '',
          })),
          summary: '',
          private_notes: '',
          recommendation: null,
          overall_rating: null,
        },
      },
    )
    expect(legacyRecordCreated.status()).toBe(201)

    await page.getByTestId('nav-candidates').click()
    await expect(page.getByTestId('talent-list')).toBeVisible()
    const talentRow = page.getByTestId(`talent-row-${application.candidate.id}`)
    await expect(talentRow).toBeVisible()
    await expect(talentRow).toContainText(interviewCandidateName)
    await expect(talentRow).not.toContainText(`e2e-interview-candidate-r${testInfo.retry}@example.test`)
    await talentRow.click()
    await page.getByTestId('add-shared-activity').click()
    await page.getByTestId('activity-content').fill('HR 留言：已完成初談，請資訊技術部主管確認技術深度。')
    const hrActivitySaved = page.waitForResponse(response =>
      response.url().includes('/api/v1/candidates/')
      && response.url().endsWith('/activities')
      && response.request().method() === 'POST',
    )
    await page.getByTestId('activity-submit').click()
    expect((await hrActivitySaved).status()).toBe(201)
    await expect(page.getByTestId('shared-activity-timeline')).toContainText('HR 留言：已完成初談')
    await page.getByRole('button', { name: '關閉人才詳情' }).click()

    let analysisPostCount = 0
    page.on('request', request => {
      if (
        request.method() === 'POST'
        && /\/deidentified-resumes\/\d+\/analyses\//.test(request.url())
      ) analysisPostCount += 1
    })
    await page.getByTestId('nav-matching').click()
    await expect(page.getByTestId('unified-talent-workspace')).toBeVisible()
    await page.getByTestId('matching-job-select').selectOption(targetJobId!)
    await page.getByTestId('matching-source-applicants').click()
    const matchingRow = page.getByTestId(`match-row-toggle-${application.candidate.id}`)
    await expect(matchingRow).toBeVisible()
    await matchingRow.click()
    const candidateAnalysisPanel = page.getByTestId('candidate-analysis-panel')
    await expect(candidateAnalysisPanel).toBeVisible()
    await expect(candidateAnalysisPanel).toContainText('只有最後按下 A 或 B 才會開始計算與使用 Token')
    expect(analysisPostCount).toBe(0)
    await page.getByTestId(`matching-open-interview-${application.candidate.id}`).click()
    await expect(page.getByTestId('unified-workspace-mode-interviews')).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByTestId(`interview-row-toggle-${application.id}`)).toHaveAttribute('aria-expanded', 'true')
    expect(analysisPostCount).toBe(0)

    const hrApplicationCard = await expandInterviewApplication(page, application.id)
    await expect(hrApplicationCard).toContainText(interviewCandidateName)
    await hrApplicationCard.getByTestId(`interview-edit-${application.id}-hr`).click()
    const hrInterviewForm = hrApplicationCard.getByTestId(`interview-form-${application.id}-hr`)
    await hrInterviewForm.getByTestId('interview-at-input').fill('2026-08-20T14:30')
    await hrInterviewForm.getByTestId('interview-result-select').selectOption('advance')
    await hrInterviewForm.getByTestId('interview-notes').fill('HR 已確認技術面試，請主管參與。')
    const hrInterviewSaved = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/applications/${application.id}/interviews/hr`)
      && response.request().method() === 'PATCH',
    )
    await hrInterviewForm.getByTestId('interview-save').click()
    const hrInterviewResponse = await hrInterviewSaved
    expect(hrInterviewResponse.status()).toBe(200)
    const hrInterview = await hrInterviewResponse.json()
    expect(hrInterview.hr_interview.interview_at).toBeTruthy()
    expect(hrInterview.hr_interview.interview_result).toBe('advance')
    expect(hrInterview.hr_interview.interview_notes).toBe('HR 已確認技術面試，請主管參與。')
    expect(hrInterview.manager_interview.interview_at).toBeNull()
    await expect(page.getByTestId('interview-success')).toContainText(interviewCandidateName)
    await expect(hrApplicationCard).toContainText('HR 已確認技術面試，請主管參與。')
    await expect(hrApplicationCard).toContainText(legacyHrQuestion)

    const hrQuestionRegenerated = page.waitForResponse(response => (
      response.url().includes(`/api/v1/applications/${application.id}/interview-question-plan/questions/0/regenerate`)
      && response.url().includes('stage=hr')
      && response.request().method() === 'POST'
    ))
    await hrApplicationCard.getByTestId(`question-regenerate-${application.id}-hr-0`).click()
    const hrQuestionResponse = await hrQuestionRegenerated
    expect(hrQuestionResponse.status()).toBe(200)
    const generatedHrPlan = await hrQuestionResponse.json() as {
      questions: Array<{ question: string }>
    }
    await expect(hrApplicationCard).toContainText('題目版本 v1')
    await expect(hrApplicationCard).toContainText(generatedHrPlan.questions[0].question)
    await expect(hrApplicationCard).not.toContainText(legacyHrQuestion)
    await hrApplicationCard.getByTestId(`question-stage-${application.id}-manager`).click()
    await expect(hrApplicationCard.getByTestId(`question-plan-generate-${application.id}-manager`)).toHaveCount(0)

    await page.getByRole('button', { name: '登出' }).click()
    await page.getByLabel('帳號或 Email').fill('it_manager')
    await page.getByLabel('密碼').fill('dept123')
    await page.getByRole('button', { name: '登入工作台' }).click()
    for (const testId of ['nav-department', 'nav-resumes', 'nav-matching']) {
      await expect(page.getByTestId(testId)).toBeVisible()
    }
    await expect(page.getByTestId('nav-interviews')).toHaveCount(0)
    await expect(page.getByTestId('nav-candidates')).toHaveCount(0)
    await expect(page.getByTestId('nav-admin')).toHaveCount(0)

    await page.getByTestId('nav-department').click()
    await page.getByRole('button', { name: /資深後端工程師/ }).click()
    await expect(page.getByText(interviewCandidateName, { exact: true })).toBeVisible()

    const managerLogin = await request.post(`${backendApi}/auth/login`, {
      data: { username: 'it_manager', password: 'dept123' },
    })
    expect(managerLogin.ok()).toBeTruthy()
    const managerToken = (await managerLogin.json()).access_token as string
    const managerActivitySaved = await request.post(
      `${backendApi}/candidates/${application.candidate.id}/activities`,
      {
        headers: { Authorization: `Bearer ${managerToken}` },
        data: {
          type: '主管留言',
          content: '主管留言：技術面試將加強系統設計與協作能力確認。',
        },
      },
    )
    expect(managerActivitySaved.status()).toBe(201)

    await page.getByTestId('nav-resumes').click()
    await expect(page.getByRole('heading', { name: '新增履歷並指派職缺' })).toBeVisible()
    await openUnifiedInterviews(page)
    const managerApplicationCard = await expandInterviewApplication(page, application.id)
    await expect(managerApplicationCard).toContainText(interviewCandidateName)
    await expect(managerApplicationCard).toContainText('HR 已確認技術面試，請主管參與。')
    await managerApplicationCard.getByTestId(`question-stage-${application.id}-hr`).click()
    await expect(managerApplicationCard.locator('.question-preview-list li')).toHaveCount(5)
    await expect(managerApplicationCard.getByTestId(`question-plan-generate-${application.id}-hr`)).toHaveCount(0)
    await managerApplicationCard.getByTestId(`question-stage-${application.id}-manager`).click()
    const managerQuestionGenerated = page.waitForResponse(response => (
      response.url().includes(`/api/v1/applications/${application.id}/interview-question-plan/generate`)
      && response.url().includes('stage=manager')
      && response.request().method() === 'POST'
    ))
    await managerApplicationCard.getByTestId(`question-plan-generate-${application.id}-manager`).click()
    expect((await managerQuestionGenerated).status()).toBe(200)
    await expect(managerApplicationCard.locator('.question-preview-list li')).toHaveCount(5)
    const managerQuestionsBefore = await managerApplicationCard.locator('.question-preview-list li strong').allTextContents()
    const managerQuestionRegenerated = page.waitForResponse(response => (
      response.url().includes(`/api/v1/applications/${application.id}/interview-question-plan/questions/1/regenerate`)
      && response.url().includes('stage=manager')
      && response.request().method() === 'POST'
    ))
    await managerApplicationCard.getByTestId(`question-regenerate-${application.id}-manager-1`).click()
    const managerRegeneratedResponse = await managerQuestionRegenerated
    expect(managerRegeneratedResponse.status()).toBe(200)
    const managerRegeneratedPlan = await managerRegeneratedResponse.json() as {
      questions: Array<{ question: string }>
      version: number
    }
    expect(managerRegeneratedPlan.version).toBe(2)
    expect(managerRegeneratedPlan.questions[1].question).not.toBe(managerQuestionsBefore[1])
    expect(managerRegeneratedPlan.questions.filter((_, index) => index !== 1).map(item => item.question)).toEqual(
      managerQuestionsBefore.filter((_, index) => index !== 1),
    )
    await expect(managerApplicationCard).toContainText('題目版本 v2')
    await managerApplicationCard.getByTestId(`interview-edit-${application.id}-manager`).click()
    const managerInterviewForm = managerApplicationCard.getByTestId(`interview-form-${application.id}-manager`)
    await managerInterviewForm.getByTestId('interview-at-input').fill('2026-08-21T10:00')
    await managerInterviewForm.getByTestId('interview-result-select').selectOption('hold')
    await managerInterviewForm.getByTestId('interview-notes').fill('資訊技術部主管已完成初談，暫列保留。')
    const managerInterviewSaved = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/applications/${application.id}/interviews/manager`)
      && response.request().method() === 'PATCH',
    )
    await managerInterviewForm.getByTestId('interview-save').click()
    const managerInterviewResponse = await managerInterviewSaved
    expect(managerInterviewResponse.status()).toBe(200)
    const managerInterview = await managerInterviewResponse.json()
    expect(managerInterview.hr_interview.interview_notes).toBe('HR 已確認技術面試，請主管參與。')
    expect(managerInterview.manager_interview.interview_result).toBe('hold')
    expect(managerInterview.manager_interview.interview_notes).toBe('資訊技術部主管已完成初談，暫列保留。')
    await expect(page.getByTestId('interview-success')).toContainText(interviewCandidateName)

    await page.getByRole('button', { name: '登出' }).click()
    await page.getByLabel('帳號或 Email').fill('e2e-hr')
    await page.getByLabel('密碼').fill('E2E-HR-Password-123!')
    await page.getByRole('button', { name: '登入工作台' }).click()
    await openUnifiedInterviews(page)
    const hrReviewCard = await expandInterviewApplication(page, application.id)
    await hrReviewCard.getByTestId(`question-stage-${application.id}-manager`).click()
    await expect(hrReviewCard.locator('.question-preview-list li')).toHaveCount(5)
    await expect(hrReviewCard.getByTestId(`question-plan-generate-${application.id}-manager`)).toHaveCount(0)
    await page.getByTestId('nav-candidates').click()
    await page.getByRole('button', { name: new RegExp(interviewCandidateName) }).click()
    await expect(page.getByTestId('shared-activity-timeline')).toContainText('主管留言：技術面試將加強')
    await expect(page.getByTestId('shared-activity-timeline')).toContainText('資訊技術部主管')
    await page.getByRole('button', { name: '關閉人才詳情' }).click()

    await page.getByRole('button', { name: '登出' }).click()
    await page.getByLabel('帳號或 Email').fill('design')
    await page.getByLabel('密碼').fill('dept123')
    await page.getByRole('button', { name: '登入工作台' }).click()
    await openUnifiedInterviews(page)
    await expect(page.getByTestId(`interview-application-${application.id}`)).toHaveCount(0)
    await expect(page.getByText(interviewCandidateName, { exact: true })).toHaveCount(0)
  })

  test('department manager creates an own-department job that global recruiting can see', async ({ page }, testInfo) => {
    const departmentJobName = departmentJobNameFor(testInfo.retry)
    await page.goto('http://127.0.0.1:4173')
    await page.getByLabel('帳號或 Email').fill('it_manager')
    await page.getByLabel('密碼').fill('dept123')
    await page.getByRole('button', { name: '登入工作台' }).click()

    await expect(page.getByRole('heading', { name: '資訊技術部' })).toBeVisible()
    await page.getByRole('button', { name: '＋ 建立本部門職缺' }).click()
    await page.getByLabel('職缺名稱 *').fill(departmentJobName)
    await page.getByLabel('工作地點 *').fill('台北市')
    await page.getByLabel('技能條件').fill('Python, AWS, SQL')
    await page.getByLabel('職務說明（JD）*').fill('由部門主管建立並送交 HR 核准的端對端測試職缺。')
    await page.getByRole('button', { name: '建立並送交 HR' }).click()
    await expect(page.getByText(/已建立並送交 HR 核准/)).toBeVisible()
    await expect(page.getByRole('heading', { name: departmentJobName })).toBeVisible()

    await page.getByRole('button', { name: /資深後端工程師/ }).click()
    await expect(page.getByText('展示人才－林怡君')).toBeVisible()
    for (const testId of ['nav-department', 'nav-resumes', 'nav-matching']) {
      await expect(page.getByTestId(testId)).toBeVisible()
    }
    await expect(page.getByTestId('nav-interviews')).toHaveCount(0)
    await expect(page.getByTestId('nav-candidates')).toHaveCount(0)
    await expect(page.getByTestId('nav-admin')).toHaveCount(0)

    await page.getByRole('button', { name: '登出' }).click()
    await page.getByLabel('帳號或 Email').fill('e2e-admin')
    await page.getByLabel('密碼').fill('E2E-Admin-Password-123!')
    await page.getByRole('button', { name: '登入工作台' }).click()
    await page.getByRole('button', { name: '職缺管理' }).click()
    await expect(page.getByRole('heading', { name: departmentJobName })).toBeVisible()
  })

  test('HR can blind-rate the isolated small-sample matching benchmark', async ({ page }) => {
    await page.goto('http://127.0.0.1:4173')
    await page.getByLabel('帳號或 Email').fill('e2e-hr')
    await page.getByLabel('密碼').fill('E2E-HR-Password-123!')
    await page.getByRole('button', { name: '登入工作台' }).click()

    await page.getByTestId('nav-matching').click()
    await expect(page.getByTestId('matching-open-benchmark')).toBeVisible()
    await page.getByTestId('matching-open-benchmark').click()

    await expect(page.getByRole('heading', { name: '媒合盲評基準' })).toBeVisible()
    await expect(page.locator('.case-card')).toHaveCount(10)
    await expect(page.locator('.result-table')).toHaveCount(0)
    await expect(page.getByText('系統分數', { exact: true })).toHaveCount(0)

    const firstCase = page.locator('.case-card').first()
    await firstCase.getByLabel('能力證據明確').check()
    const ratingSaved = page.waitForResponse(response => (
      response.url().includes('/api/v1/matching-benchmark/suites/')
      && response.url().endsWith('/my-rating')
      && response.request().method() === 'PUT'
    ))
    await firstCase.getByRole('button', { name: '儲存這一題' }).click()
    expect((await ratingSaved).status()).toBe(200)
    await expect(firstCase.getByText('已評分', { exact: true })).toBeVisible()
    await expect(page.getByText(/畫面仍不會顯示系統分數/)).toBeVisible()
  })
})
