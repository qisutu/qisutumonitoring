from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TranslationRuntimeTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js required')
    def test_all_catalogs_static_dynamic_and_user_values(self):
        script = r'''
const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert');
const root=process.argv[1];
for(const file of fs.readdirSync(path.join(root,'languages')).filter(x=>x.endsWith('.json'))){
 const pack=JSON.parse(fs.readFileSync(path.join(root,'languages',file),'utf8'));
 const texts=[{nodeValue:'  Geräte  ',parentElement:{closest(){return null;}}}];
 const attribute={attrs:{title:'Agenten'},closest(){return null;},hasAttribute(k){return k in this.attrs;},getAttribute(k){return this.attrs[k];},setAttribute(k,v){this.attrs[k]=v;}};
 const document={documentElement:{},createTreeWalker(){let index=0;return{nextNode:()=>texts[index++]||null};},querySelectorAll(){return[attribute];}};
 const ctx={window:{QISUTU_LOCALE:pack},document,NodeFilter:{SHOW_TEXT:4}};vm.createContext(ctx);
 vm.runInContext(fs.readFileSync(path.join(root,'static/i18n.js'),'utf8'),ctx);
 const run=code=>vm.runInContext(code,ctx);
 assert.equal(document.documentElement.lang,pack.code);
 assert.equal(run('T("Geräte")'),pack.messages['Geräte']);
 assert.equal(run('T("  Geräte  ")'),'  '+pack.messages['Geräte']+'  ');
 run('I18N.static(document)');assert.equal(texts[0].nodeValue,'  '+pack.messages['Geräte']+'  ');
 assert.equal(attribute.attrs.title,pack.messages['Agenten']);
 const output=run('H`<button title="Schließen">Geräte</button><span>${"&lt;script&gt;Geräte&lt;/script&gt;"}</span>`');
 assert(output.includes(pack.messages['Geräte']));
 assert(output.includes('&lt;script&gt;Geräte&lt;/script&gt;'));
 assert(!output.includes('&amp;lt;script'));assert(!output.includes('<script>'));
 assert.equal(run('H`<span>&lt; 5 &amp; &gt; 1</span>`'),'<span>&lt; 5 &amp; &gt; 1</span>');
 assert(run('T("Agent „{0}“ löschen?", "Geräte")').includes('Geräte'));
 assert.equal(run('H`<option value="${"de"}">${"Geräte"}</option>`'),'<option value="de">Geräte</option>');
 assert.equal(run('T("literal user data {9}")'),'literal user data {9}');
 assert(run('T("{0} ausgewählt", 3)').includes('3'));
}
console.log('All 11 catalogs, static labels, placeholders, escaping and unchanged user data verified.');
'''
        result = subprocess.run(['node', '-e', script, str(ROOT/'netzmonitor')],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
