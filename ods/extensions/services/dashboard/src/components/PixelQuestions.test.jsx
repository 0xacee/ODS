import {useState} from 'react'
import {render,screen,fireEvent} from '@testing-library/react'
import {describe,it,expect,vi} from 'vitest'
import PixelQuestions from './PixelQuestions'
import {parseQuestionsFrame,questionMetadata,answersMessage} from '../lib/pixelQuestions'
const questions=[{id:'style',question:'Qual estilo?',options:['Clean','Colorido']},{id:'pages',question:'Quantas páginas?',options:['Uma','Três']}]
function Fixture({onSubmit,...props}) {
  const [answers,setAnswers]=useState({})
  return <PixelQuestions questions={questions} answers={answers} onChange={setAnswers} onSubmit={onSubmit} {...props}/>
}
describe('choice cards',()=>{
  it('requires actual choices, supports custom text and submits both answers once',()=>{
    const submit=vi.fn();render(<Fixture onSubmit={submit}/>);
    expect(screen.getByRole('button',{name:'Next'})).toBeDisabled();
    fireEvent.click(screen.getByRole('radio',{name:/Clean/}));
    fireEvent.click(screen.getByRole('button',{name:'Next'}));
    fireEvent.click(screen.getByRole('radio',{name:'Write another answer'}));
    fireEvent.change(screen.getByRole('textbox',{name:'Your answer'}),{target:{value:'Duas páginas'}});
    fireEvent.click(screen.getByRole('button',{name:'Continue'}));
    expect(submit).toHaveBeenCalledWith('Qual estilo?\nClean\n\nQuantas páginas?\nDuas páginas');
  });
  it('retains answers when navigating back and disables old conversation questions',()=>{
    const {rerender}=render(<Fixture onSubmit={()=>{}}/>);
    fireEvent.click(screen.getByRole('radio',{name:/Colorido/}));fireEvent.click(screen.getByRole('button',{name:'Next'}));
    fireEvent.click(screen.getByRole('button',{name:'Previous question'}));
    expect(screen.getByRole('radio',{name:/Colorido/})).toBeChecked();
    rerender(<Fixture onSubmit={()=>{}} answered/>);
    expect(screen.queryByRole('button',{name:'Continue'})).not.toBeInTheDocument();
  });
  it('only accepts terminal structured frames; drafts persist as bounded text',()=>{
    expect(parseQuestionsFrame({choices:[{finish_reason:null}],pixel_questions:{schemaVersion:1,questions}})).toBeNull();
    expect(parseQuestionsFrame({choices:[{finish_reason:'stop'}],pixel_questions:{schemaVersion:1,questions}})).toEqual(questions);
    expect(questionMetadata({role:'assistant',questions,questionDraft:{style:'Clean'}}).questionDraft.style).toBe('Clean');
    expect(answersMessage(questions,{style:'Clean'})).toBeNull();
  });
});
