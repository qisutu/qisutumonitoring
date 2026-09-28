"""User controls stay reachable in the collapsed sidebar and use safe text nodes."""
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProfileUITests(unittest.TestCase):
    def test_actual_profile_controls_and_events(self):
        class Markup(HTMLParser):
            def __init__(self):
                super().__init__(); self.ids=[]
            def handle_starttag(self, tag, attrs):
                attrs=dict(attrs)
                if 'id' in attrs: self.ids.append(attrs['id'])
        markup=Markup(); markup.feed((ROOT/'netzmonitor/static/index.html').read_text())
        self.assertEqual(len(markup.ids), len(set(markup.ids)))
        script=r'''
const fs=require('fs'), vm=require('vm'), assert=require('assert');
const ids=JSON.parse(process.argv[1]), elements={}, events={};
for(const id of ids)elements[id]={hidden:true,textContent:'',value:'',attrs:{},handlers:{},
 addEventListener(type,cb){this.handlers[type]=cb},setAttribute(k,v){this.attrs[k]=v},
 querySelector(){return{ textContent:''}},showModal(){this.open=true},close(){this.open=false},
 focus(){this.focused=true},scrollIntoView(){},replaceChildren(){},reset(){},
 elements:{current:{focus(){}}}};
const context={console,$:id=>{assert.ok(elements[id],id);return elements[id]},
 currentAgent:{name:'Ada Lovelace <img onerror=x>',username:'ada'},
 document:{addEventListener:(type,cb)=>events[type]=cb},I18N:{language:'en',locale:'en-GB'},
 T:s=>s,esc:s=>s,setupDirty:false,confirm:()=>true,requestAnimationFrame:cb=>cb(),
 tab:n=>{context.lastTab=n;elements['view-'+n].hidden=false}};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),context);
vm.runInContext('renderAgentIdentity()',context);
assert.equal(elements['current-agent'].textContent,context.currentAgent.name);
assert.equal(elements['sidebar-user-avatar'].textContent,'AL');
assert.equal(elements['sidebar-user-menu-name'].textContent,context.currentAgent.name);
elements['sidebar-user-avatar'].onclick();
assert.equal(elements['sidebar-user-menu'].hidden,false);
assert.equal(elements['sidebar-user-avatar'].attrs['aria-expanded'],'true');
assert.ok(elements['profile-menu'].focused);
events.keydown({key:'Escape'});assert.ok(elements['sidebar-user-menu'].hidden);
assert.ok(elements['sidebar-user-avatar'].focused);
elements['sidebar-user-avatar'].onclick();
events.click({target:{closest:()=>null}});assert.ok(elements['sidebar-user-menu'].hidden);
elements['profile-menu'].onclick();assert.ok(elements['profile-dialog'].open);
assert.equal(elements['profile-language'].value,'en');
assert.ok(elements['sidebar-user-menu'].hidden);
elements['profile-password'].onclick();assert.equal(context.lastTab,'settings');
assert.equal(elements['profile-dialog'].open,false);
context.currentAgent=null;vm.runInContext('clearAgents()',context);
assert.equal(elements['current-agent'].textContent,'');
assert.equal(elements['sidebar-user-avatar'].textContent,'');
assert.equal(elements['sidebar-user-menu-name'].textContent,'');
'''
        result=subprocess.run(['node','-e',script,json.dumps(markup.ids),str(ROOT/'netzmonitor/static/agents.js')],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__ == '__main__':
    unittest.main()
