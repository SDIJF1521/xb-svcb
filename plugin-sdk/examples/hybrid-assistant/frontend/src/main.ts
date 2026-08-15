import { host, isHosted } from '@xb-svcb/plugin-sdk/client'
import './style.css'

function element<T extends Element>(selector: string): T {
  const value = document.querySelector<T>(selector)
  if (!value) throw new Error(`缺少页面元素：${selector}`)
  return value
}

const output = element<HTMLPreElement>('#output')
const button = element<HTMLButtonElement>('#create')

button.addEventListener('click', async () => {
  if (!isHosted()) {
    output.textContent = '当前是浏览器开发预览；安装插件后可调用真实 Python 动作。'
    return
  }
  button.disabled = true
  try {
    const result = await host.runAction('create', {
      source_path: element<HTMLInputElement>('#source_path').value,
      model_id: element<HTMLInputElement>('#model_id').value,
      title: element<HTMLInputElement>('#title').value,
      style: element<HTMLSelectElement>('#style').value,
    })
    output.textContent = JSON.stringify(result, null, 2)
  } catch (error) {
    output.textContent = error instanceof Error ? error.message : String(error)
  } finally {
    button.disabled = false
  }
})
