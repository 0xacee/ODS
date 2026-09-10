import { render, screen, fireEvent, act } from '@testing-library/react'
import PixelDictation from './PixelDictation'

afterEach(() => { delete window.SpeechRecognition; delete window.webkitSpeechRecognition })
function speech() {
  const instance = {start:vi.fn(),abort:vi.fn()}
  window.SpeechRecognition = function () { return instance }
  return instance
}
test('starts only on explicit click and inserts final dictation without sending', () => {
  const instance = speech(), insert = vi.fn()
  render(<PixelDictation onInsert={insert} conversationId="one"/>)
  expect(instance.start).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button',{name:'Dictate message'}))
  expect(instance.start).toHaveBeenCalledOnce()
  act(() => instance.onresult({results:[Object.assign([{transcript:'Hello Pixel'}],{isFinal:true})]}))
  expect(insert).toHaveBeenCalledWith('Hello Pixel ')
  act(() => instance.onend())
  expect(screen.getByRole('button',{name:'Dictate message'})).toHaveAttribute('aria-pressed','false')
})
test('stops on conversation changes and discards late results', () => {
  const instance = speech(), insert = vi.fn()
  const view = render(<PixelDictation onInsert={insert} conversationId="one"/>)
  fireEvent.click(screen.getByRole('button',{name:'Dictate message'}))
  view.rerender(<PixelDictation onInsert={insert} conversationId="two"/>)
  expect(instance.abort).toHaveBeenCalledOnce()
  act(() => instance.onresult({results:[[{transcript:'late text'}]]}))
  expect(insert).not.toHaveBeenCalled()
})
test('reports unsupported browsers without changing the draft', () => {
  const insert = vi.fn()
  render(<PixelDictation onInsert={insert}/>)
  fireEvent.click(screen.getByRole('button',{name:'Dictate message'}))
  expect(screen.getByRole('status')).toHaveTextContent('not supported')
  expect(insert).not.toHaveBeenCalled()
})
test('reports denied permission and aborts recognition on unmount', () => {
  const instance = speech()
  const view = render(<PixelDictation onInsert={() => {}}/>)
  fireEvent.click(screen.getByRole('button',{name:'Dictate message'}))
  act(() => instance.onerror({error:'not-allowed'}))
  expect(screen.getByRole('status')).toHaveTextContent('not granted')
  fireEvent.click(screen.getByRole('button',{name:'Dictate message'}))
  view.unmount()
  expect(instance.abort).toHaveBeenCalledOnce()
})

test('Stop dictation finalizes captured speech before returning to idle', () => {
  const instance=speech(),insert=vi.fn()
  instance.stop=vi.fn()
  render(<PixelDictation conversationId="one" onInsert={insert}/>)
  fireEvent.click(screen.getByRole('button',{name:'Dictate message'}))
  fireEvent.click(screen.getByRole('button',{name:'Stop dictation'}))
  expect(instance.stop).toHaveBeenCalledOnce()
  expect(instance.abort).not.toHaveBeenCalled()
  expect(screen.getByRole('button',{name:'Finishing dictation'})).toBeDisabled()
  act(() => {
    instance.onresult({resultIndex:0,results:[Object.assign([{transcript:'Keep these words'}],{isFinal:true})]})
    instance.onend()
  })
  expect(insert).toHaveBeenCalledWith('Keep these words ')
  expect(screen.getByRole('button',{name:'Dictate message'})).toBeEnabled()
})
test('appends only newly finalized results', () => {
  const instance=speech(),insert=vi.fn()
  render(<PixelDictation onInsert={insert}/>)
  fireEvent.click(screen.getByRole('button',{name:'Dictate message'}))
  const first=Object.assign([{transcript:'First'}],{isFinal:true})
  const second=Object.assign([{transcript:'Second'}],{isFinal:true})
  act(() => instance.onresult({resultIndex:0,results:[first]}))
  act(() => instance.onresult({resultIndex:1,results:[first,second]}))
  expect(insert.mock.calls).toEqual([['First '],['Second ']])
})
test('changing conversation during finalization aborts and rejects the old result', () => {
  const instance=speech(),insert=vi.fn()
  instance.stop=vi.fn()
  const view=render(<PixelDictation conversationId="one" onInsert={insert}/>)
  fireEvent.click(screen.getByRole('button',{name:'Dictate message'}))
  fireEvent.click(screen.getByRole('button',{name:'Stop dictation'}))
  view.rerender(<PixelDictation conversationId="two" onInsert={insert}/>)
  act(() => instance.onresult({results:[[{transcript:'old words'}]]}))
  expect(instance.abort).toHaveBeenCalledOnce()
  expect(insert).not.toHaveBeenCalled()
  expect(screen.getByRole('button',{name:'Dictate message'})).toBeEnabled()
})
