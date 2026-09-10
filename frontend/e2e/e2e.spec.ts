import { expect, test, type Page } from '@playwright/test';

// 端到端冒烟（plan_four §3 收尾）：登录 → 建库 → 上传 → SSE 问答 → 引用跳转预览。
// 前置：make up + make migrate + make seed-admin（默认 admin/changeme）。
// 走真实后端 + 真实 embedding/LLM。串行执行（用例间有状态依赖）。
// 注：AntD 双字按钮自动插入空格（登录→"登 录"），按钮名用 \s* 正则匹配。

const KB_NAME = 'E2E 测试库';
// 内容每次运行唯一：后端按 (tenant, checksum) 内容去重，重复上传会 409。
// txt 首行会被解析为文档标题——表格标题列/引用卡片展示的都是它（非文件名）
const RUN = Date.now().toString(36);
const DOC_NAME = 'e2e_zephyr.txt';
const DOC_TITLE = `Zephyr 数据平台白皮书（E2E-${RUN}）`;
const DOC_CONTENT = [
  DOC_TITLE,
  'Zephyr 平台的核心组件包括：向量子阵、混合检索融合、重排序器。',
  'Zephyr 平台的故障恢复依赖幂等消费者与至少一次语义的消息队列。',
  'Zephyr 平台的默认嵌入模型维度为 1024，采用归一化余弦相似度。',
  `（E2E 运行标记 ${RUN}）`,
].join('\n');

async function login(page: Page) {
  await page.goto('/login');
  await page.getByLabel('用户名').fill('admin');
  await page.getByLabel('密码').fill('changeme');
  await page.getByRole('button', { name: /登\s*录/ }).click();
  await expect(page).toHaveURL(/\/chat/);
  // 顶栏用户菜单显示用户名（strict mode：与角色 Tag 同名，取第一个）
  await expect(page.getByText('admin', { exact: true }).first()).toBeVisible();
}

async function ensure_kb(page: Page) {
  await page.goto('/knowledge-bases');
  // 先等列表接口返回再判断存在性：此前在数据到达前 count=0 → 误判去创建 →
  // 撞后端重名 409（后端已把重名从 500 收敛为 409 duplicate_knowledge_base）
  await page.waitForResponse(
    (r) => r.url().includes('/api/v1/knowledge-bases?') && r.request().method() === 'GET',
  );
  const cell = page.getByRole('cell', { name: KB_NAME, exact: true });
  if ((await cell.count()) === 0) {
    await page.getByRole('button', { name: /新建/ }).click();
    await page.getByLabel('名称').fill(KB_NAME);
    await page.getByRole('button', { name: /创\s*建/ }).click(); // Modal okText
  }
  await expect(cell.first()).toBeVisible();
}

/** 主区域知识库 Select 选中 E2E 库。
 *  不点 option（rc-select 虚拟列表与 Playwright actionability 常见打架：
 *  option 解析到隐藏挂载节点上永远 not visible），改用键盘 typeahead：
 *  非搜索型 Select 支持按 label 前缀打字选中。 */
async function select_kb(page: Page) {
  await page.getByRole('main').getByRole('combobox').click();
  await page.keyboard.type('E2E');
  await page.keyboard.press('Enter');
  await expect(
    page.getByRole('main').locator('.ant-select-selection-item', { hasText: KB_NAME }),
  ).toBeVisible();
}

test.describe.serial('RAG 前端 E2E', () => {
  test('未登录访问受保护页 → 跳登录页', async ({ page }) => {
    await page.goto('/chat');
    await expect(page).toHaveURL(/\/login/);
  });

  test('错误密码 → 提示失败且不跳转', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('用户名').fill('admin');
    await page.getByLabel('密码').fill('wrong-password');
    await page.getByRole('button', { name: /登\s*录/ }).click();
    await expect(page.getByText(/invalid credentials|登录失败/)).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
  });

  test('登录成功 → 进入聊天页', async ({ page }) => {
    await login(page);
  });

  test('创建知识库（幂等复用）', async ({ page }) => {
    await login(page);
    await ensure_kb(page);
  });

  test('上传文档 → 异步管线 → indexed', async ({ page }) => {
    test.setTimeout(120_000); // 真实 embedding（外部 API）+ Kafka 异步管线
    await login(page);
    await ensure_kb(page);

    await page.goto('/documents');
    await select_kb(page);

    await page.setInputFiles('input[type=file]', [
      { name: DOC_NAME, mimeType: 'text/plain', buffer: Buffer.from(DOC_CONTENT) },
    ]);
    // 上传成功提示（预签名不可达时自动降级后端直传）
    await expect(page.getByText('已上传，正在解析…')).toBeVisible({ timeout: 30_000 });

    // 状态列推进：pending → parsing/chunking/embedding → indexed（按本次唯一标题定位行）
    const row = page.getByRole('row', { name: new RegExp(DOC_TITLE) });
    await expect(row).toBeVisible();
    await expect(row.getByText('indexed', { exact: true })).toBeVisible({ timeout: 90_000 });
  });

  test('SSE 问答：流式回答 + 引用命中上传文档', async ({ page }) => {
    test.setTimeout(180_000); // agentic 检索 + 真实 LLM 流式生成
    await login(page);

    await select_kb(page); // 聊天页知识库选择
    await page.getByPlaceholder('输入问题，回车发送').fill('Zephyr 平台的故障恢复依赖什么？');
    await page.getByRole('button', { name: /发\s*送/ }).click();

    // 引用面板先于生成完成到达：命中 Zephyr 白皮书（引用卡片展示解析标题）
    await expect(page.getByText('引用来源：')).toBeVisible({ timeout: 120_000 });
    await expect(page.getByText(/Zephyr 数据平台白皮书/).first()).toBeVisible();

    // 流式 token：助手气泡积累出与语料相关的文本
    await expect(
      page.getByText(/幂等消费者|消息队列|至少一次/, { exact: false }).last(),
    ).toBeVisible({ timeout: 120_000 });
  });

  test('PDF 引用预览：pdfjs 渲染 + bbox 定位信息', async ({ page }) => {
    test.setTimeout(180_000);
    test.skip(!(await pdfAvailable()), '栈内无 PDF 文档（先上传一份再跑本用例）');
    await login(page);
    await page.getByPlaceholder('输入问题，回车发送').fill('2026年第三季度的营收是多少？');
    await page.getByRole('button', { name: /发\s*送/ }).click();

    const link = page.getByRole('link', { name: /查看原文/ }).first();
    await expect(link).toBeVisible({ timeout: 120_000 });
    await link.click();

    // pdfjs 渲染出 canvas + 定位信息行
    await expect(page.locator('canvas').first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/区域级溯源/)).toBeVisible();
  });
});

/** 栈里是否存在 PDF 文档（表格冒烟的季报）——按列表探测，失败视为无。 */
async function pdfAvailable(): Promise<boolean> {
  try {
    const r = await fetch('http://localhost:8000/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: 'admin', password: 'changeme' }),
    });
    const { access_token } = await r.json();
    const docs = await fetch('http://localhost:8000/api/v1/documents?page_size=100', {
      headers: { Authorization: `Bearer ${access_token}` },
    }).then((x) => x.json());
    return (docs.items || []).some(
      (d: { title: string; content_type: string }) =>
        /\.pdf$/i.test(d.title) || d.content_type === 'application/pdf',
    );
  } catch {
    return false;
  }
}
