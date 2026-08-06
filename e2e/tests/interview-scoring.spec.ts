import { expect, test, type Locator, type Page } from '@playwright/test'

// Sibling spec to talent-flow.spec.ts: that chain covers intake -> resume -> review,
// this one covers the structured scoring contract in docs/13 (per-question 1-5
// rating, draft/submit/reopen, blind review and the composite score). It owns its
// own candidate and application so a failure here never blocks that chain, and it
// creates the HR account itself so either file can run first.
const backendApi = 'http://127.0.0.1:8018/api/v1'
const hrWorkspace = 'http://127.0.0.1:4173'

const scoringCandidateNameFor = (retry: number) => `E2E 評分流程人才 R${retry}`
const hrResponseFor = (retry: number, index: number) => `HR 記錄 R${retry}：第 ${index + 1} 題候選人陳述`
const managerResponseFor = (retry: number, index: number) => `主管記錄 R${retry}：第 ${index + 1} 題候選人陳述`
const hrObservationFor = (retry: number) => `HR 觀察 R${retry}：成本估算依據待查證`
const hrSummaryFor = (retry: number) => `HR 總評 R${retry}：跨部門遷移證據充分`
const hrRevisedSummaryFor = (retry: number) => `${hrSummaryFor(retry)}；補充第二題追問結果`
const managerSummaryFor = (retry: number) => `主管總評 R${retry}：系統設計深度符合職務需求`
const notAskedReason = '時間不足，改由主管複試確認'
const reopenReason = '補正第二題的評分依據後需要重新提交'

// 4 + 3 + 5 + 4 over the four questions that were actually asked is 80. The same
// five questions with the 未詢問 one counted as a zero would be 64, which is the
// number docs/13 §9.1 forbids. Keep the ratings if the expectations change.
const hrRatings = [
  { score: 4, label: '優於期待' },
  { score: 3, label: '符合期待' },
  { score: 5, label: '卓越表現' },
  { score: 4, label: '優於期待' },
] as const
const managerRating = { score: 4, label: '優於期待' } as const
const hrQuestionScore = '80'
const hrOverallScore = '82'
const managerOverallScore = '78'
// resume 20% is excluded (no match result for a hand-added candidate), so the
// remaining weights renormalise to 18.75/31.25/18.75/31.25 over 80/82/80/78.
const compositeScore = '80'
const zeroFilledCompositeScore = '64'

// Shared by the serial steps below. Playwright reruns the whole serial group on
// retry, so every step derives its text from testInfo.retry and these are rebuilt.
let applicationId = 0
let hrRecordId = 0
let hrRecordPlanVersion: number | null = null

async function signIn(page: Page, username: string, password: string) {
  await page.goto(hrWorkspace)
  await page.getByLabel('帳號或 Email').fill(username)
  await page.getByLabel('密碼').fill(password)
  await page.getByRole('button', { name: '登入工作台' }).click()
}

// Same navigation and expansion helpers as talent-flow.spec.ts. Deliberately
// duplicated rather than shared so neither spec can break the other by editing them.
async function openUnifiedInterviews(page: Page) {
  await page.getByTestId('nav-matching').click()
  const workspace = page.getByTestId('unified-talent-workspace')
  await expect(workspace).toBeVisible()
  await workspace.getByTestId('unified-workspace-mode-interviews').click()
  await expect(workspace.getByTestId('unified-workspace-mode-interviews')).toHaveAttribute(
    'aria-selected',
    'true',
  )
  await expect(page.getByTestId('interview-management')).toBeVisible()
}

async function expandInterviewApplication(page: Page, id: number) {
  const card = page.getByTestId(`interview-application-${id}`)
  await expect(card).toBeVisible()
  const toggle = card.getByTestId(`interview-row-toggle-${id}`)
  // A background sync of the application list re-renders the workspace and can
  // close the row again, so keep re-opening it until it stays open.
  await expect(async () => {
    if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click()
    await expect(toggle).toHaveAttribute('aria-expanded', 'true', { timeout: 2_000 })
  }).toPass({ timeout: 20_000 })
  return card
}

async function openScoringCard(page: Page, stage: 'hr' | 'manager') {
  await openUnifiedInterviews(page)
  const card = await expandInterviewApplication(page, applicationId)
  await card.getByTestId(`question-stage-${applicationId}-${stage}`).click()
  await expect(card.getByTestId(`question-stage-${applicationId}-${stage}`)).toHaveAttribute(
    'aria-selected',
    'true',
  )
  return card
}

function recordForm(card: Locator) {
  return card.getByTestId('interview-record-form')
}

// The five question cards carry no test id. Their rating fieldset does expose a
// legend, which is a stable accessible name, so each question is addressed
// through role + accessible name instead of the .record-question-card class.
function ratingGroup(form: Locator, index: number) {
  return form.getByRole('group', { name: `第 ${index + 1} 題評分` })
}

function ratingRadio(form: Locator, index: number, rating: { score: number; label: string }) {
  return ratingGroup(form, index).getByRole('radio', { name: `${rating.score} 分：${rating.label}` })
}

async function rateQuestion(form: Locator, index: number, rating: { score: number; label: string }) {
  // The radio itself is clipped to 1px for styling; clicking its visible label
  // text is what an interviewer actually does.
  await ratingGroup(form, index).getByText(rating.label, { exact: true }).click()
  await expect(ratingRadio(form, index, rating)).toBeChecked()
}

function questionResponse(form: Locator, index: number) {
  return form.getByLabel('面試過程回答紀錄').nth(index)
}

function scoreOverviewRows(card: Locator) {
  return card.getByRole('list').filter({ hasText: '⑥ 綜合參考分' }).getByRole('listitem')
}

async function openScoreOverview(card: Locator) {
  await card.getByText('六項分數總覽', { exact: true }).click()
  await expect(card.getByText(/六項都是 0–100 分制/)).toBeVisible()
}

async function openRecordMeta(card: Locator) {
  await card.getByText('紀錄資訊', { exact: true }).click()
}

test.describe.serial('結構化面試評分、盲評與綜合分', () => {
  test('HR 逐題評分草稿可儲存，重新整理後答案與分數都回填', async ({ page, request }, testInfo) => {
    test.setTimeout(120_000)
    const candidateName = scoringCandidateNameFor(testInfo.retry)

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

    await signIn(page, 'e2e-hr', 'E2E-HR-Password-123!')
    await expect(page.getByTestId('intake-route-guide')).toBeVisible()

    await page.getByTestId('nav-candidates').click()
    await page.getByRole('button', { name: /手動新增人才/ }).click()
    await expect(page.getByRole('heading', { name: '新增人才' })).toBeVisible()
    await page.getByLabel('姓名 *').fill(candidateName)
    await page.getByLabel('Email').fill(`e2e-scoring-candidate-r${testInfo.retry}@example.test`)
    await page.getByLabel('目前職稱').fill('後端工程師')
    const departmentSelect = page.getByTestId('candidate-department-select')
    const jobSelect = page.getByTestId('candidate-job-select')
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
      candidate: { name: string }
      requisition: { title: string; department_name: string | null }
    }
    expect(application.candidate.name).toBe(candidateName)
    expect(application.requisition.department_name).toBe('資訊技術部')
    applicationId = application.id

    const card = await openScoringCard(page, 'hr')
    const form = recordForm(card)
    // The HR stage opens on the standard five questions, so there is nothing to
    // generate: the scoring form is ready as soon as the card expands.
    await expect(card.getByTestId(`question-plan-generate-${applicationId}-hr`)).toHaveCount(0)
    await expect(ratingGroup(form, 4)).toBeVisible()

    for (const [index, rating] of hrRatings.entries()) {
      await questionResponse(form, index).fill(hrResponseFor(testInfo.retry, index))
      await rateQuestion(form, index, rating)
    }
    await form.getByText('對應特質與面試官觀察', { exact: true }).first().click()
    await form.getByLabel('面試官觀察（評分區）').first().fill(hrObservationFor(testInfo.retry))

    // The fifth question was never put to the candidate: no rating, mandatory reason.
    await ratingGroup(form, 4).getByText('未詢問', { exact: true }).click()
    await expect(ratingGroup(form, 4).getByRole('radio', { name: '未詢問此題' })).toBeChecked()
    await form.getByLabel('未詢問原因').fill(notAskedReason)

    const draftSaved = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/applications/${applicationId}/interview-records`)
      && response.request().method() === 'POST',
    )
    await form.getByTestId('interview-record-save-draft').click()
    const draftResponse = await draftSaved
    expect(draftResponse.status()).toBe(201)
    const draftRecord = await draftResponse.json() as {
      id: number
      status: string
      revision_number: number
      question_plan_version: number | null
      questions: Array<{ rating: number | null; not_asked_reason: string | null; response: string | null }>
    }
    expect(draftRecord.status).toBe('in_progress')
    expect(draftRecord.revision_number).toBe(0)
    expect(draftRecord.questions.map(question => question.rating)).toEqual([4, 3, 5, 4, null])
    expect(draftRecord.questions[4].not_asked_reason).toBe(notAskedReason)
    // The standard HR five are not a stored plan, so the record is bound to no
    // version until someone regenerates a question (see the last test).
    expect(draftRecord.question_plan_version).toBeNull()
    hrRecordId = draftRecord.id
    hrRecordPlanVersion = draftRecord.question_plan_version
    await expect(card.getByText('面試草稿已建立')).toBeVisible()

    // The regression this spec exists for: a saved draft has to survive a full
    // page load and come back into the same editor, answers and ratings included.
    await page.reload()
    const reloadedCard = await openScoringCard(page, 'hr')
    const reloadedForm = recordForm(reloadedCard)
    for (const [index, rating] of hrRatings.entries()) {
      await expect(questionResponse(reloadedForm, index)).toHaveValue(hrResponseFor(testInfo.retry, index))
      await expect(ratingRadio(reloadedForm, index, rating)).toBeChecked()
    }
    await expect(reloadedForm.getByLabel('面試官觀察（評分區）').first()).toHaveValue(hrObservationFor(testInfo.retry))
    await expect(ratingGroup(reloadedForm, 4).getByRole('radio', { name: '未詢問此題' })).toBeChecked()
    await expect(reloadedForm.getByLabel('未詢問原因')).toHaveValue(notAskedReason)
    await expect(reloadedForm.getByTestId('interview-record-save-draft')).toBeVisible()
  })

  test('未詢問的題目不計入題目分數：四題 4、3、5、4 為 80 分而非 64 分', async ({ page }) => {
    await signIn(page, 'e2e-hr', 'E2E-HR-Password-123!')
    const card = await openScoringCard(page, 'hr')
    const form = recordForm(card)

    // Same arithmetic, second rendering: the editor's own reference line averages
    // over the rated questions only, so it is 4.0 / 5 and not 3.2 / 5.
    await expect(form.getByText('題目平均 4.0 / 5（5/5 題已評分或略過）', { exact: false })).toBeVisible()

    await openScoreOverview(card)
    const questionScoreRow = scoreOverviewRows(card).filter({ hasText: 'HR 題目' })
    await expect(questionScoreRow).toContainText(hrQuestionScore)
    await expect(questionScoreRow).toContainText('4 題已評分，未詢問不計入')
    await expect(questionScoreRow).not.toContainText(zeroFilledCompositeScore)
  })

  test('提交後轉為唯讀，必須填寫原因才能重新開啟，再次提交會遞增修訂編號', async ({ page, request }, testInfo) => {
    test.setTimeout(120_000)
    const hrLogin = await request.post(`${backendApi}/auth/login`, {
      data: { username: 'e2e-hr', password: 'E2E-HR-Password-123!' },
    })
    expect(hrLogin.ok()).toBeTruthy()
    const hrToken = (await hrLogin.json()).access_token as string

    await signIn(page, 'e2e-hr', 'E2E-HR-Password-123!')
    const card = await openScoringCard(page, 'hr')
    const form = recordForm(card)

    await form.getByLabel('面試總分').fill(hrOverallScore)
    await form.getByLabel('錄用建議').selectOption('offer')
    await form.getByLabel('面試總評').fill(hrSummaryFor(testInfo.retry))
    const submitted = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/applications/${applicationId}/interview-records/${hrRecordId}`)
      && response.request().method() === 'PATCH',
    )
    await form.getByTestId('interview-record-submit').click()
    const submitResponse = await submitted
    expect(submitResponse.status()).toBe(200)
    const submittedRecord = await submitResponse.json() as { status: string; revision_number: number }
    expect(submittedRecord.status).toBe('completed')
    expect(submittedRecord.revision_number).toBe(1)

    // Read-only means the controls are gone, not merely disabled.
    await expect(card.getByText('這筆評分已提交，內容為唯讀')).toBeVisible()
    await expect(form.getByTestId('interview-record-save-draft')).toHaveCount(0)
    await expect(form.getByTestId('interview-record-submit')).toHaveCount(0)
    await expect(form.getByLabel('面試過程回答紀錄')).toHaveCount(0)
    await expect(form.getByTestId('interview-record-reopen')).toBeVisible()
    await expect(card).toContainText(hrResponseFor(testInfo.retry, 0))
    await expect(card).toContainText('4 / 5 分')
    await expect(card).toContainText(`未詢問：${notAskedReason}`)

    // Reopening without a reason is refused in the browser and by the API.
    await form.getByTestId('interview-record-reopen').click()
    const reopenPanel = card.getByRole('region', { name: '重新開啟評分' })
    const confirmReopen = reopenPanel.getByRole('button', { name: '確認重新開啟' })
    await expect(confirmReopen).toBeDisabled()
    await reopenPanel.getByLabel('重新開啟原因').fill('   ')
    await expect(confirmReopen).toBeDisabled()
    const blankReasonRejected = await request.post(
      `${backendApi}/applications/${applicationId}/interview-records/${hrRecordId}/reopen`,
      { headers: { Authorization: `Bearer ${hrToken}` }, data: { reason: '   ' } },
    )
    expect(blankReasonRejected.status()).toBe(422)

    await reopenPanel.getByLabel('重新開啟原因').fill(reopenReason)
    const reopened = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/applications/${applicationId}/interview-records/${hrRecordId}/reopen`)
      && response.request().method() === 'POST',
    )
    await confirmReopen.click()
    const reopenResponse = await reopened
    expect(reopenResponse.status()).toBe(200)
    const reopenedRecord = await reopenResponse.json() as {
      status: string
      revision_number: number
      last_reopen_reason: string
    }
    expect(reopenedRecord.status).toBe('in_progress')
    // docs/13 §5.5: reopening keeps the revision number; only resubmission raises it.
    expect(reopenedRecord.revision_number).toBe(1)
    expect(reopenedRecord.last_reopen_reason).toBe(reopenReason)
    await expect(form.getByTestId('interview-record-submit')).toBeVisible()

    await form.getByLabel('面試總評').fill(hrRevisedSummaryFor(testInfo.retry))
    const resubmitted = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/applications/${applicationId}/interview-records/${hrRecordId}`)
      && response.request().method() === 'PATCH',
    )
    await form.getByTestId('interview-record-submit').click()
    const resubmitResponse = await resubmitted
    expect(resubmitResponse.status()).toBe(200)
    const resubmittedRecord = await resubmitResponse.json() as {
      status: string
      revision_number: number
      summary: string
    }
    expect(resubmittedRecord.status).toBe('completed')
    expect(resubmittedRecord.revision_number).toBe(2)
    expect(resubmittedRecord.summary).toBe(hrRevisedSummaryFor(testInfo.retry))

    await openRecordMeta(card)
    const recordMeta = card.getByTestId(`interview-question-progress-${applicationId}`)
    await expect(recordMeta.getByText('紀錄修訂')).toBeVisible()
    await expect(recordMeta).toContainText('#2')
    await expect(recordMeta).toContainText(reopenReason)
    await expect(form.getByTestId('interview-record-save-draft')).toHaveCount(0)
  })

  test('只有 HR 提交時，主管看不到 HR 的評分、觀察、總評與建議，也沒有綜合分', async ({ page }, testInfo) => {
    await signIn(page, 'it_manager', 'dept123')
    const card = await openScoringCard(page, 'hr')
    const form = recordForm(card)

    // Shared question-and-answer stays readable; every evaluation field is masked.
    await expect(card).toContainText(hrResponseFor(testInfo.retry, 0))
    await expect(card.getByText('評分與觀察待主管提交後自動顯示')).toHaveCount(5)
    await expect(card).not.toContainText(hrSummaryFor(testInfo.retry))
    await expect(card).not.toContainText(hrObservationFor(testInfo.retry))
    await expect(card).not.toContainText('建議發 Offer')
    await expect(card).not.toContainText('4 / 5 分')
    await expect(card).not.toContainText('5 / 5 分')
    // docs/13 §12 lists an unmasked 未詢問原因 as a release blocker: it leaks the
    // other side's judgement just as a rating does.
    await expect(card).not.toContainText(notAskedReason)
    await expect(card).not.toContainText(reopenReason)
    await expect(form.getByLabel('面試總分')).toHaveCount(0)
    await expect(form.getByLabel('錄用建議')).toHaveCount(0)
    await expect(form.getByLabel('面試總評')).toHaveCount(0)
    await expect(card.getByText('面試總分與錄用建議待主管提交後自動公開')).toBeVisible()
    await expect(card.getByText('HR 已提交 · 待主管提交後自動公開')).toBeVisible()

    await openScoreOverview(card)
    const questionScoreRow = scoreOverviewRows(card).filter({ hasText: 'HR 題目' })
    await expect(questionScoreRow).toContainText('—')
    await expect(questionScoreRow).toContainText('評分保護中 · 雙方提交後公開')
    await expect(questionScoreRow).not.toContainText(hrQuestionScore)
    const overallScoreRow = scoreOverviewRows(card).filter({ hasText: 'HR 總結' })
    await expect(overallScoreRow).toContainText('—')
    await expect(overallScoreRow).not.toContainText(hrOverallScore)

    // One stage in is never enough for a composite, and the gap is never a zero.
    const compositeRow = scoreOverviewRows(card).filter({ hasText: '綜合參考分' })
    await expect(compositeRow).toContainText('—')
    await expect(compositeRow).toContainText('等待主管提交；未齊前不顯示任何部分計算結果')
    await expect(compositeRow).not.toContainText('0')
    await expect(card.getByText('等待主管提交', { exact: true })).toBeVisible()
    await expect(card.getByText('面試綜合分 · 參考值')).toHaveCount(0)
  })

  test('主管提交後雙方評分與綜合分才出現，缺少的項目不以 0 分計', async ({ page, request }, testInfo) => {
    test.setTimeout(120_000)
    await signIn(page, 'it_manager', 'dept123')
    const card = await openScoringCard(page, 'manager')
    const form = recordForm(card)

    const planGenerated = page.waitForResponse(response => (
      response.url().includes(`/api/v1/applications/${applicationId}/interview-question-plan/generate`)
      && response.url().includes('stage=manager')
      && response.request().method() === 'POST'
    ))
    await card.getByTestId(`question-plan-generate-${applicationId}-manager`).click()
    const planResponse = await planGenerated
    expect(planResponse.status()).toBe(200)
    // A generated question has to fit the interview-record schema it will be saved
    // through (source is capped at 200 characters there). When it does not, the
    // interviewer fills in the whole form and the submission fails with a 422 on
    // content the system produced itself.
    const generatedPlan = await planResponse.json() as { questions: Array<{ question: string; source: string | null }> }
    for (const question of generatedPlan.questions) {
      expect(question.source?.length ?? 0, `題目依據超過紀錄欄位長度：${question.source}`).toBeLessThanOrEqual(200)
    }
    await expect(ratingGroup(form, 4)).toBeVisible()

    for (let index = 0; index < 5; index += 1) {
      await questionResponse(form, index).fill(managerResponseFor(testInfo.retry, index))
      await rateQuestion(form, index, managerRating)
    }
    await form.getByLabel('面試總分').fill(managerOverallScore)
    await form.getByLabel('錄用建議').selectOption('advance')
    await form.getByLabel('面試總評').fill(managerSummaryFor(testInfo.retry))
    const managerSubmitted = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/applications/${applicationId}/interview-records`)
      && response.request().method() === 'POST',
    )
    await form.getByTestId('interview-record-submit').click()
    const managerSubmitResponse = await managerSubmitted
    expect(managerSubmitResponse.status()).toBe(201)
    const managerRecord = await managerSubmitResponse.json() as { status: string; revision_number: number }
    expect(managerRecord.status).toBe('completed')
    expect(managerRecord.revision_number).toBe(1)

    // Blind review releases automatically: HR's evaluation is now readable, and
    // read-only, on the HR tab.
    const hrTabCard = await openScoringCard(page, 'hr')
    const hrTabForm = recordForm(hrTabCard)
    await expect(hrTabForm.getByLabel('面試總評')).toHaveValue(hrRevisedSummaryFor(testInfo.retry))
    await expect(hrTabForm.getByLabel('面試總評')).toBeDisabled()
    await expect(hrTabForm.getByLabel('面試總分')).toHaveValue(hrOverallScore)
    await expect(hrTabForm.getByLabel('錄用建議')).toHaveValue('offer')
    await expect(hrTabCard).toContainText('4 / 5 分')
    await expect(hrTabCard).toContainText(`面試官觀察：${hrObservationFor(testInfo.retry)}`)
    await expect(hrTabCard).toContainText(`未詢問：${notAskedReason}`)
    await expect(hrTabCard.getByText('雙方已提交 · 評分已公開')).toBeVisible()

    // composite_score is stored on the application, so re-read the list.
    const applicationsReloaded = page.waitForResponse(response => (
      /\/api\/v1\/applications(\?|$)/.test(response.url())
      && response.request().method() === 'GET'
    ))
    await page.getByTestId('interviews-refresh').click()
    expect((await applicationsReloaded).status()).toBe(200)
    const refreshedCard = await expandInterviewApplication(page, applicationId)
    await openScoreOverview(refreshedCard)
    const compositeRow = scoreOverviewRows(refreshedCard).filter({ hasText: '綜合參考分' })
    await expect(compositeRow).toContainText(compositeScore)
    await expect(compositeRow).not.toContainText(zeroFilledCompositeScore)
    await expect(compositeRow).toContainText('僅供排序與討論參考')
    // A hand-added candidate never went through matching: the resume component is
    // absent, and absent has to render as a dash with the reason stated, never as
    // a zero that drags the composite down (docs/13 §9.1).
    const resumeRow = scoreOverviewRows(refreshedCard).filter({ hasText: '履歷匹配' })
    await expect(resumeRow).toContainText('—')
    await expect(resumeRow).toContainText('此人才未經媒合計算')
    await expect(refreshedCard).toContainText('已排除（無媒合紀錄）')
    await expect(refreshedCard.getByText('面試綜合分 · 參考值')).toBeVisible()

    // Third rendering of the per-question arithmetic: the number the backend
    // stored has to be the same 80 the two browser views showed.
    const hrLogin = await request.post(`${backendApi}/auth/login`, {
      data: { username: 'e2e-hr', password: 'E2E-HR-Password-123!' },
    })
    expect(hrLogin.ok()).toBeTruthy()
    const applications = await request.get(`${backendApi}/applications`, {
      headers: { Authorization: `Bearer ${(await hrLogin.json()).access_token}` },
    })
    expect(applications.ok()).toBeTruthy()
    const stored = (await applications.json() as Array<{
      id: number
      composite_score: number | null
      composite_score_breakdown: {
        status: string
        components: Record<string, { value: number | null; included: boolean; excluded_reason: string | null }>
      } | null
    }>).find(item => item.id === applicationId)
    expect(stored?.composite_score).toBe(Number(compositeScore))
    expect(stored?.composite_score_breakdown?.status).toBe('computed')
    expect(stored?.composite_score_breakdown?.components.hr_questions.value).toBe(Number(hrQuestionScore))
    expect(stored?.composite_score_breakdown?.components.resume.included).toBe(false)
    expect(stored?.composite_score_breakdown?.components.resume.value).toBeNull()
    expect(stored?.composite_score_breakdown?.components.resume.excluded_reason).toBe('no_match_result')
  })

  test('重新產生題目後，既有評分紀錄仍可找到並重新開啟修改', async ({ page }, testInfo) => {
    test.setTimeout(120_000)
    await signIn(page, 'e2e-hr', 'E2E-HR-Password-123!')
    const card = await openScoringCard(page, 'hr')

    const regenerated = page.waitForResponse(response => (
      response.url().includes(`/api/v1/applications/${applicationId}/interview-question-plan/questions/0/regenerate`)
      && response.url().includes('stage=hr')
      && response.request().method() === 'POST'
    ))
    await card.getByTestId(`question-regenerate-${applicationId}-hr-0`).click()
    const regenerateResponse = await regenerated
    expect(regenerateResponse.status()).toBe(200)
    // First stored HR plan for this application, so the card now shows v1 while
    // the submitted record is still bound to the standard questions.
    expect((await regenerateResponse.json() as { version: number }).version).toBe(1)
    await expandInterviewApplication(page, applicationId)
    await expect(card).toContainText('題目版本 v1')

    // The bug this guards: the card moved on to a question plan the saved record
    // is not bound to, and a lookup keyed on that plan made the record unreachable.
    await page.reload()
    const reloadedCard = await openScoringCard(page, 'hr')
    const reloadedForm = recordForm(reloadedCard)
    await expect(reloadedCard).toContainText('已載入你先前填寫的內容（題目版本較舊）')
    await expect(reloadedForm.getByLabel('面試總評')).toHaveValue(hrRevisedSummaryFor(testInfo.retry))
    await expect(reloadedForm.getByTestId('interview-record-reopen')).toBeVisible()

    await reloadedForm.getByTestId('interview-record-reopen').click()
    const reopenPanel = reloadedCard.getByRole('region', { name: '重新開啟評分' })
    await reopenPanel.getByLabel('重新開啟原因').fill('題目改版後確認舊紀錄仍可修改')
    const reopened = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/applications/${applicationId}/interview-records/${hrRecordId}/reopen`)
      && response.request().method() === 'POST',
    )
    await reopenPanel.getByRole('button', { name: '確認重新開啟' }).click()
    expect((await reopened).status()).toBe(200)

    // Reopened against the version it was scored on, with every answer intact.
    for (const [index, rating] of hrRatings.entries()) {
      await expect(questionResponse(reloadedForm, index)).toHaveValue(hrResponseFor(testInfo.retry, index))
      await expect(ratingRadio(reloadedForm, index, rating)).toBeChecked()
    }
    await expect(reloadedForm.getByLabel('未詢問原因')).toHaveValue(notAskedReason)

    const resubmitted = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/applications/${applicationId}/interview-records/${hrRecordId}`)
      && response.request().method() === 'PATCH',
    )
    await reloadedForm.getByTestId('interview-record-submit').click()
    const resubmitResponse = await resubmitted
    expect(resubmitResponse.status()).toBe(200)
    const resubmittedRecord = await resubmitResponse.json() as {
      revision_number: number
      question_plan_version: number | null
    }
    expect(resubmittedRecord.revision_number).toBe(3)
    // docs/13 §7.4: reopening never rebinds the record to the newer question set.
    expect(resubmittedRecord.question_plan_version).toBe(hrRecordPlanVersion)
  })
})
