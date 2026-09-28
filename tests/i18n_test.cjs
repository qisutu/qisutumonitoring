// Load the real German runtime in the small existing Node/VM UI harnesses.
const fs=require('fs'),path=require('path'),vm=require('vm');
const context={window:{QISUTU_LOCALE:JSON.parse(fs.readFileSync(path.join(__dirname,'../netzmonitor/languages/de.json'),'utf8'))},document:{documentElement:{}}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../netzmonitor/static/i18n.js'),'utf8'),context);
for(const name of ['T','H','I18N'])globalThis[name]=vm.runInContext(name,context);
const original=vm.createContext;
vm.createContext=function(target,...args){
 for(const name of ['T','H','I18N'])target[name]=globalThis[name];
 return original.call(vm,target,...args);
};
