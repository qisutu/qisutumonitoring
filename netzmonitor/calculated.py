"""Arithmetic over current stored measurements without eval or executable code."""
import ast
import math
import operator
import re
import time

from .integration_common import CheckFailure, metric

OPS={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv,ast.Mod:operator.mod}
FUNCTIONS={'min':min,'max':max,'abs':abs,'round':round}


def validate_expression(expression,names):
    if not isinstance(expression,str) or len(expression)>1000 or len(names)!=len(set(names)) or any(not re.fullmatch('[a-z][a-z0-9_]{0,30}',n) or n in FUNCTIONS for n in names):
        raise ValueError('Ungültige Formel oder Variablennamen.')
    try:tree=ast.parse(expression,mode='eval')
    except SyntaxError:raise ValueError('Ungültige Formel.')
    nodes=list(ast.walk(tree))
    if len(nodes)>100:raise ValueError('Formel ist zu umfangreich.')
    for node in nodes:
        if isinstance(node,ast.Name) and node.id not in set(names)|set(FUNCTIONS):raise ValueError('Unbekannte Formelvariable.')
        if isinstance(node,ast.Constant) and (not isinstance(node.value,(float,int)) or isinstance(node.value,bool) or abs(node.value)>1e15):raise ValueError('Ungültige Formelkonstante.')
        if isinstance(node,ast.Call) and (not isinstance(node.func,ast.Name) or node.func.id not in FUNCTIONS or node.keywords or not 1<=len(node.args)<=20):raise ValueError('Unzulässige Formelfunktion.')
        if not isinstance(node,(ast.Expression,ast.BinOp,ast.UnaryOp,ast.UAdd,ast.USub,ast.Constant,ast.Name,ast.Load,ast.Call,*OPS.keys())):raise ValueError('Unzulässiger Formelausdruck.')
    return tree


def evaluate(expression,values):
    tree=validate_expression(expression,list(values))
    def visit(node):
        if isinstance(node,ast.Expression):return visit(node.body)
        if isinstance(node,ast.Constant):return node.value
        if isinstance(node,ast.Name):return values[node.id]
        if isinstance(node,ast.BinOp):return OPS[type(node.op)](visit(node.left),visit(node.right))
        if isinstance(node,ast.UnaryOp):return (-1 if isinstance(node.op,ast.USub) else 1)*visit(node.operand)
        if isinstance(node,ast.Call):return FUNCTIONS[node.func.id](*[visit(a) for a in node.args])
        raise ValueError('Ungültige Formel.')
    value=visit(tree)
    if not math.isfinite(value):raise ValueError('Formelergebnis ist keine endliche Zahl.')
    return value


def calculated(store,cfg):
    queries={
        'integration':"SELECT m.value,m.status,t.last_checked,t.interval,t.timeout,t.enabled,d.enabled AS device_enabled,d.blocked,d.license_blocked FROM integration_metrics m JOIN integration_targets t ON t.id=m.target_id JOIN devices d ON d.id=t.device_id WHERE m.id=? AND m.active=1",
        'extended':"SELECT m.value,m.status,m.last_checked,t.interval,t.timeout,t.enabled,d.enabled AS device_enabled,d.blocked,d.license_blocked FROM extended_metrics m JOIN resource_targets t ON t.id=m.target_id JOIN devices d ON d.id=t.device_id WHERE m.id=? AND m.enabled=1",
        'resource':"SELECT m.percent AS value,m.status,t.last_checked,t.interval,t.timeout,t.enabled,d.enabled AS device_enabled,d.blocked,d.license_blocked FROM resource_metrics m JOIN resource_targets t ON t.id=m.target_id JOIN devices d ON d.id=t.device_id WHERE m.id=?",
        'service':"SELECT t.rtt AS value,t.status,t.last_checked,t.interval,t.timeout,t.enabled,d.enabled AS device_enabled,d.blocked,d.license_blocked FROM services t JOIN devices d ON d.id=t.device_id WHERE t.id=?",
    }
    values={};now=time.time()
    try:
        for source in cfg['sources']:
            rows=store.rows(queries[source['route']],(source['id'],))
            if not rows:raise CheckFailure('Eine Quellmessreihe fehlt.')
            row=rows[0]
            if row['value'] is None or row['status'] not in ('up','warning','critical') or not row['enabled'] or not row['device_enabled'] or row['blocked'] or row['license_blocked'] or not row['last_checked'] or now-row['last_checked']>min(cfg['max_age'],max(60,row['interval']+row['timeout']+30)):
                raise CheckFailure('Eine Quellmessreihe fehlt, ist pausiert oder veraltet.')
            values[source['name']]=row['value']
        value=evaluate(cfg['expression'],values)
        return dict(kind='ok',metrics=[metric('calculated','Berechneter Messwert',value,cfg['unit'],warn=cfg['warn'],critical=cfg['critical'])],message='')
    except (CheckFailure,ValueError,ZeroDivisionError,OverflowError,TypeError,KeyError) as exc:
        return dict(kind='error',metrics=[],message=str(exc))
