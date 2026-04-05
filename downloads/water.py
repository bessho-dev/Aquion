#!/usr/bin/env python3
"""
Water Language Interpreter
Usage:
  python water.py              # REPL mode
  python water.py script.water # File execution
"""
import sys, math, time, threading, os, re, copy

# ═══════════════════════════════════════════════════════════════
# TOKENS
# ═══════════════════════════════════════════════════════════════
KEYWORDS = {
    'usefor','sl','inport','set','free','stay','dic','list','depthlist',
    'stayto','liststayto','add','delete','change','deplist','depsearch',
    'if','elif','else','in','match','makeset','print','input','clear',
    'ercall','go','fin','back','repeat','let','return',
    'call','callend','frcall','frcallend','vset','out',
    'wait','math','compute','sin','cos','tan','unit_conversion',
    'move','borrow','borrow_mut','as','to','all','num',
    'true','false','and','or','not','value','CV',
}

class Token:
    __slots__ = ('type','value','line')
    def __init__(self, t, v, ln=0):
        self.type = t; self.value = v; self.line = ln
    def __repr__(self):
        return f'T({self.type},{self.value!r})'

class Lexer:
    def __init__(self, src):
        self.tokens = []
        self._tokenize(src)
        self.pos = 0

    def _tokenize(self, src):
        lines = src.replace('\r\n','\n').replace('\r','\n').split('\n')
        indent_stack = [0]
        for ln, raw in enumerate(lines, 1):
            line = raw.rstrip()
            if not line or line.lstrip().startswith('#'):
                continue
            stripped = line.lstrip()
            raw_indent = line[:len(line)-len(stripped)]
            indent = len(raw_indent.replace('\t','    '))
            if indent > indent_stack[-1]:
                indent_stack.append(indent)
                self.tokens.append(Token('INDENT','',ln))
            while indent < indent_stack[-1]:
                indent_stack.pop()
                self.tokens.append(Token('DEDENT','',ln))
            self._scan_line(stripped, ln)
            self.tokens.append(Token('NL','',ln))
        while len(indent_stack) > 1:
            indent_stack.pop()
            self.tokens.append(Token('DEDENT','',ln if lines else 0))
        self.tokens.append(Token('EOF','',0))

    def _scan_line(self, s, ln):
        i = 0
        while i < len(s):
            c = s[i]
            if c in ' \t': i+=1; continue
            if c == '#': break
            if c in ('"',"'"):
                q=c; i+=1; buf=''
                while i<len(s) and s[i]!=q:
                    if s[i]=='\\' and i+1<len(s):
                        nx=s[i+1]
                        buf+={'n':'\n','t':'\t','\\':'\\','"':'"',"'":"'"}.get(nx,nx)
                        i+=2
                    else: buf+=s[i]; i+=1
                i+=1
                self.tokens.append(Token('STR',buf,ln)); continue
            if c.isdigit() or (c=='.' and i+1<len(s) and s[i+1].isdigit()):
                j=i; dot=False
                while j<len(s) and (s[j].isdigit() or (s[j]=='.' and not dot)):
                    if s[j]=='.': dot=True
                    j+=1
                v=float(s[i:j]) if dot else int(s[i:j])
                self.tokens.append(Token('NUM',v,ln)); i=j; continue
            if c.isalpha() or c=='_':
                j=i
                while j<len(s) and (s[j].isalnum() or s[j]=='_'): j+=1
                w=s[i:j]
                tt=w.upper() if w in KEYWORDS else 'ID'
                if w=='CV': tt='CV'
                if w in ('true','false'): tt='BOOL'
                self.tokens.append(Token(tt, w, ln)); i=j; continue
            if i+1<len(s):
                two=s[i:i+2]
                op2={'==':'EQ','!=':'NEQ','<=':'LE','>=':'GE','+=':'PLUSEQ','-=':'MINUSEQ','=>':'ARROW'}
                if two in op2:
                    self.tokens.append(Token(op2[two],two,ln)); i+=2; continue
            op1={'=':'ASSIGN','+':'PLUS','-':'MINUS','*':'STAR','/':'SLASH','%':'MOD',
                 '<':'LT','>':'GT','(':'LP',')':'RP','[':'LB',']':'RB',
                 '{':'LC','}':'RC',':':'COLON',',':'COMMA','.':'DOT','_':'UNDER'}
            if c in op1:
                self.tokens.append(Token(op1[c],c,ln)); i+=1; continue
            raise SyntaxError(f"Unexpected char '{c}' at line {ln}")

    def peek(self, offset=0):
        p=self.pos+offset
        return self.tokens[p] if p<len(self.tokens) else Token('EOF','',0)
    def eat(self, *types):
        t=self.peek()
        if types and t.type not in types:
            raise SyntaxError(f"Expected {types}, got {t.type}({t.value!r}) at line {t.line}")
        self.pos+=1; return t
    def at(self, *types): return self.peek().type in types
    def skip_nl(self):
        while self.at('NL','INDENT','DEDENT'): self.eat()

# ═══════════════════════════════════════════════════════════════
# AST NODES
# ═══════════════════════════════════════════════════════════════
class N: pass
class Program(N):
    def __init__(s, stmts): s.stmts=stmts
class UseforStmt(N):
    def __init__(s,p): s.purpose=p
class SlInportStmt(N):
    def __init__(s,n): s.name=n
class SetStmt(N):
    def __init__(s,kind,name,typ=None,val=None): s.kind=kind;s.name=name;s.typ=typ;s.val=val
class StaytoStmt(N):
    def __init__(s,n,t): s.name=n;s.new_type=t
class ListstaytoStmt(N):
    def __init__(s,n,t): s.name=n;s.new_type=t
class ListOpStmt(N):
    def __init__(s,n,op,**kw): s.name=n;s.op=op;s.kw=kw
class DeplistOpStmt(N):
    def __init__(s,n,op,**kw): s.name=n;s.op=op;s.kw=kw
class IfStmt(N):
    def __init__(s,cond,body,elifs,elseb): s.cond=cond;s.body=body;s.elifs=elifs;s.elseb=elseb
class MatchStmt(N):
    def __init__(s,expr,arms): s.expr=expr;s.arms=arms
class PrintStmt(N):
    def __init__(s,e): s.expr=e
class InputExpr(N):
    def __init__(s,prompt,typ=None): s.prompt=prompt;s.typ=typ
class ClearStmt(N): pass
class ErcallStmt(N):
    def __init__(s,guarded,action): s.guarded=guarded;s.action=action
class RepeatStmt(N):
    def __init__(s,count,body,cond_mode=None,cond_val=True):
        s.count=count;s.body=body;s.cond_mode=cond_mode;s.cond_val=cond_val
class LetStmt(N):
    def __init__(s,n,v): s.name=n;s.val=v
class AssignStmt(N):
    def __init__(s,n,v,op='='): s.name=n;s.val=v;s.op=op
class FuncDef(N):
    def __init__(s,kind,name,params,body,vsets=None):
        s.kind=kind;s.name=name;s.params=params;s.body=body;s.vsets=vsets or[]
class ReturnStmt(N):
    def __init__(s,vals): s.vals=vals
class VsetStmt(N):
    def __init__(s,d,ext,intr): s.dir=d;s.ext=ext;s.intr=intr
class WaitStmt(N):
    def __init__(s,sec): s.sec=sec
class MoveStmt(N):
    def __init__(s,src,dst): s.src=src;s.dst=dst
class BorrowStmt(N):
    def __init__(s,src,dst,mut=False): s.src=src;s.dst=dst;s.mut=mut
class UnitConvStmt(N):
    def __init__(s,d): s.defn=d
class BinOp(N):
    def __init__(s,l,op,r): s.left=l;s.op=op;s.right=r
class UnaryOp(N):
    def __init__(s,op,e): s.op=op;s.expr=e
class NumLit(N):
    def __init__(s,v): s.value=v
class StrLit(N):
    def __init__(s,v): s.value=v
class BoolLit(N):
    def __init__(s,v): s.value=v
class IdExpr(N):
    def __init__(s,n): s.name=n
class CVExpr(N): pass
class ListLit(N):
    def __init__(s,elems): s.elems=elems
class DicLit(N):
    def __init__(s,pairs): s.pairs=pairs
class DepsearchExpr(N):
    def __init__(s,name,addr,mode): s.name=name;s.addr=addr;s.mode=mode
class MakesetExpr(N):
    def __init__(s,src): s.src=src
class MathComputeExpr(N):
    def __init__(s,exprs): s.exprs=exprs
class MathTrigExpr(N):
    def __init__(s,func,val,unit): s.func=func;s.val=val;s.unit=unit
class FuncCallExpr(N):
    def __init__(s,name,args): s.name=name;s.args=args
class InExpr(N):
    def __init__(s,val,container): s.val=val;s.container=container
class ScopeBlock(N):
    def __init__(s,body): s.body=body

# ═══════════════════════════════════════════════════════════════
# PARSER
# ═══════════════════════════════════════════════════════════════
class Parser:
    def __init__(s, lex):
        s.lex = lex

    def parse(s):
        stmts = s.parse_block_until('EOF')
        return Program(stmts)

    def parse_block_until(s, *end):
        stmts=[]
        while s.lex.at('NL','INDENT','DEDENT'): s.lex.eat()
        while not s.lex.at(*end):
            st = s.parse_stmt()
            if st: stmts.append(st)
            while s.lex.at('NL','INDENT','DEDENT'): s.lex.eat()
        return stmts

    def parse_indented_block(s):
        s.lex.skip_nl()
        if not s.lex.at('INDENT'):
            st = s.parse_stmt()
            return [st] if st else []
        s.lex.eat('INDENT')
        stmts = s.parse_block_until('DEDENT','EOF')
        if s.lex.at('DEDENT'): s.lex.eat('DEDENT')
        return stmts

    def parse_bracket_block(s):
        s.lex.eat('LB')
        while s.lex.at('NL','INDENT','DEDENT'): s.lex.eat()
        stmts = s.parse_block_until('RB')
        s.lex.eat('RB')
        return stmts

    def parse_brace_block(s):
        s.lex.eat('LC')
        s.lex.skip_nl()
        stmts = s.parse_block_until('RC')
        s.lex.eat('RC')
        return stmts

    def parse_stmt(s):
        s.lex.skip_nl()
        t = s.lex.peek()
        tp = t.type

        if tp=='USEFOR': return s.p_usefor()
        if tp=='SL': return s.p_sl_inport()
        if tp=='SET': return s.p_set()
        if tp=='STAYTO': return s.p_stayto()
        if tp=='LISTSTAYTO': return s.p_liststayto()
        if tp=='LIST': return s.p_list_op()
        if tp=='DEPLIST': return s.p_deplist_op()
        if tp=='IF': return s.p_if()
        if tp=='MATCH': return s.p_match()
        if tp=='PRINT': return s.p_print()
        if tp=='CLEAR': s.lex.eat(); return ClearStmt()
        if tp=='ERCALL': return s.p_ercall()
        if tp=='REPEAT': return s.p_repeat()
        if tp=='LET': return s.p_let()
        if tp in ('CALL','CALLEND','FRCALL','FRCALLEND'): return s.p_funcdef()
        if tp=='RETURN': return s.p_return()
        if tp=='VSET': return s.p_vset()
        if tp=='WAIT': return s.p_wait()
        if tp=='MOVE': return s.p_move()
        if tp in ('BORROW','BORROW_MUT'): return s.p_borrow()
        if tp=='UNIT_CONVERSION': return s.p_unitconv()
        if tp=='LC':
            s.lex.eat('LC'); s.lex.skip_nl()
            body = s.parse_block_until('RC')
            s.lex.eat('RC')
            return ScopeBlock(body)
        if tp=='ID':
            if s.lex.peek(1).type in ('ASSIGN','PLUSEQ','MINUSEQ'):
                return s.p_assign()
            e = s.parse_expr()
            return e
        e = s.parse_expr()
        return e

    # ── Statement parsers ──
    def p_usefor(s):
        s.lex.eat('USEFOR'); n=s.lex.eat('ID'); return UseforStmt(n.value)

    def p_sl_inport(s):
        s.lex.eat('SL'); s.lex.eat('DOT'); s.lex.eat('INPORT'); n=s.lex.eat('ID')
        return SlInportStmt(n.value)

    def p_set(s):
        s.lex.eat('SET'); k=s.lex.eat()
        kind=k.value
        if kind=='free':
            n=s.lex.eat('ID')
            v=None
            if s.lex.at('ASSIGN'): s.lex.eat(); v=s.parse_expr()
            return SetStmt('free',n.value,val=v)
        if kind=='stay':
            n=s.lex.eat('ID'); t=s.lex.eat('ID')
            v=None
            if s.lex.at('ASSIGN'): s.lex.eat(); v=s.parse_expr()
            return SetStmt('stay',n.value,typ=t.value,val=v)
        if kind=='dic':
            n=s.lex.eat('ID'); return SetStmt('dic',n.value)
        if kind=='list':
            n=s.lex.eat('ID')
            t=None
            if s.lex.at('ID'): t=s.lex.eat('ID').value
            return SetStmt('list',n.value,typ=t)
        if kind=='depthlist':
            n=s.lex.eat('ID'); return SetStmt('depthlist',n.value)
        raise SyntaxError(f"Unknown set kind: {kind}")

    def p_stayto(s):
        s.lex.eat('STAYTO'); n=s.lex.eat('ID'); t=s.lex.eat('ID')
        return StaytoStmt(n.value,t.value)

    def p_liststayto(s):
        s.lex.eat('LISTSTAYTO'); n=s.lex.eat('ID'); t=s.lex.eat('ID')
        return ListstaytoStmt(n.value,t.value)

    def p_list_op(s):
        s.lex.eat('LIST'); n=s.lex.eat('ID')
        op=s.lex.eat('ADD','DELETE','CHANGE')
        if op.type=='ADD':
            val=s.parse_expr()
            num=None
            if s.lex.at('NUM'): num=s.lex.eat('NUM').value
            return ListOpStmt(n.value,'add',value=val,num=num)
        if op.type=='DELETE':
            val=s.parse_expr()
            num=None
            if s.lex.at('NUM'): num=s.lex.eat('NUM').value
            return ListOpStmt(n.value,'delete',value=val,num=num)
        if op.type=='CHANGE':
            num=s.parse_expr()
            val=s.parse_expr()
            return ListOpStmt(n.value,'change',num=num,value=val)

    def p_deplist_op(s):
        s.lex.eat('DEPLIST'); n=s.lex.eat('ID')
        op=s.lex.eat('ADD','DELETE','CHANGE')
        addr=s.parse_list_literal()
        if op.type=='ADD':
            val=s.parse_expr()
            num=None
            if s.lex.at('NUM'): num=s.lex.eat('NUM').value
            return DeplistOpStmt(n.value,'add',addr=addr,value=val,num=num)
        if op.type=='DELETE':
            val=s.parse_expr()
            num=None
            if s.lex.at('NUM','ALL'):
                t=s.lex.eat(); num=t.value
            return DeplistOpStmt(n.value,'delete',addr=addr,value=val,num=num)
        if op.type=='CHANGE':
            val=s.parse_expr()
            return DeplistOpStmt(n.value,'change',addr=addr,value=val)

    def p_if(s):
        s.lex.eat('IF')
        cond=s.parse_expr()
        s.lex.eat('COLON')
        body=s.parse_indented_block()
        elifs=[]
        s.lex.skip_nl()
        while s.lex.at('ELIF'):
            s.lex.eat('ELIF')
            ec=s.parse_expr()
            s.lex.eat('COLON')
            eb=s.parse_indented_block()
            elifs.append((ec,eb))
            s.lex.skip_nl()
        elseb=None
        if s.lex.at('ELSE'):
            s.lex.eat('ELSE'); s.lex.eat('COLON')
            elseb=s.parse_indented_block()
        return IfStmt(cond,body,elifs,elseb)

    def p_match(s):
        s.lex.eat('MATCH'); expr=s.parse_expr()
        s.lex.eat('LC'); s.lex.skip_nl()
        arms=[]
        while not s.lex.at('RC'):
            if s.lex.at('UNDER'):
                s.lex.eat('UNDER'); pat='_'
            else:
                pat=s.parse_expr()
            s.lex.eat('ARROW')
            body_stmt=s.parse_stmt()
            arms.append((pat,body_stmt))
            s.lex.skip_nl()
            if s.lex.at('COMMA'): s.lex.eat('COMMA'); s.lex.skip_nl()
        s.lex.eat('RC')
        return MatchStmt(expr,arms)

    def p_print(s):
        s.lex.eat('PRINT'); s.lex.eat('LP')
        e=s.parse_expr()
        s.lex.eat('RP')
        return PrintStmt(e)

    def p_ercall(s):
        s.lex.eat('ERCALL')
        s.lex.skip_nl()
        action='go'
        if s.lex.at('INDENT'):
            s.lex.eat('INDENT')
            if s.lex.at('GO'): s.lex.eat(); action='go'
            elif s.lex.at('FIN'): s.lex.eat(); action='fin'
            elif s.lex.at('BACK'): s.lex.eat(); action='back'
            s.lex.skip_nl()
            while not s.lex.at('DEDENT','EOF'): s.lex.eat(); s.lex.skip_nl()
            if s.lex.at('DEDENT'): s.lex.eat('DEDENT')
        elif s.lex.at('GO','FIN','BACK'):
            t=s.lex.eat(); action=t.value
        return ErcallStmt(None, action)

    def p_repeat(s):
        s.lex.eat('REPEAT')
        if s.lex.at('LP'):
            s.lex.eat('LP')
            cv=s.lex.eat('BOOL')
            cond_val = cv.value=='true'
            s.lex.eat('RP')
            cond=s.parse_expr()
            body=s.parse_bracket_block()
            return RepeatStmt(cond,body,cond_mode=True,cond_val=cond_val)
        else:
            count=s.parse_expr()
            body=s.parse_bracket_block()
            return RepeatStmt(count,body)

    def p_let(s):
        s.lex.eat('LET'); n=s.lex.eat('ID'); s.lex.eat('ASSIGN')
        v=s.parse_expr()
        return LetStmt(n.value, v)

    def p_assign(s):
        n=s.lex.eat('ID'); op=s.lex.eat('ASSIGN','PLUSEQ','MINUSEQ')
        v=s.parse_expr()
        return AssignStmt(n.value, v, op.value)

    def p_funcdef(s):
        kind=s.lex.eat().value
        name=s.lex.eat().value  # Accept any token as function name
        s.lex.eat('LP')
        params=[]
        while not s.lex.at('RP'):
            params.append(s.lex.eat().value)  # Accept any token as param name
            if s.lex.at('COMMA'): s.lex.eat('COMMA')
        s.lex.eat('RP')
        body=s.parse_bracket_block()
        vsets=[]
        for st in body:
            if isinstance(st, VsetStmt): vsets.append(st)
        body=[st for st in body if not isinstance(st, VsetStmt)]
        return FuncDef(kind,name,params,body,vsets)

    def p_return(s):
        s.lex.eat('RETURN')
        vals=[]
        if not s.lex.at('NL','EOF','RB','DEDENT'):
            vals.append(s.parse_expr())
            while s.lex.at('COMMA'):
                s.lex.eat('COMMA'); vals.append(s.parse_expr())
        return ReturnStmt(vals)

    def p_vset(s):
        s.lex.eat('VSET')
        d=s.lex.eat('IN','OUT').value
        a=s.lex.eat('ID').value; s.lex.eat('ASSIGN'); b=s.lex.eat('ID').value
        if d=='in': return VsetStmt('in',a,b)
        return VsetStmt('out',a,b)

    def p_wait(s):
        s.lex.eat('WAIT'); s.lex.eat('LP')
        n=s.parse_expr()
        unit=None
        if s.lex.at('ID'): unit=s.lex.eat('ID').value
        s.lex.eat('RP')
        return WaitStmt(n)

    def p_move(s):
        s.lex.eat('MOVE'); src=s.lex.eat('ID').value
        s.lex.eat('TO'); dst=s.lex.eat('ID').value
        return MoveStmt(src,dst)

    def p_borrow(s):
        mut = s.lex.peek().type=='BORROW_MUT'
        s.lex.eat()
        src=s.lex.eat('ID').value; s.lex.eat('AS'); dst=s.lex.eat('ID').value
        return BorrowStmt(src,dst,mut)

    def p_unitconv(s):
        s.lex.eat('UNIT_CONVERSION'); s.lex.eat('LP')
        e=s.parse_expr()
        s.lex.eat('RP')
        return UnitConvStmt(e)

    def parse_list_literal(s):
        s.lex.eat('LB')
        elems=[]
        while not s.lex.at('RB'):
            elems.append(s.parse_expr())
            if s.lex.at('COMMA'): s.lex.eat('COMMA')
        s.lex.eat('RB')
        return elems

    # ── Expression parser ──
    def parse_expr(s): return s.p_or()
    def p_or(s):
        l=s.p_and()
        while s.lex.at('OR'): s.lex.eat(); l=BinOp(l,'or',s.p_and())
        return l
    def p_and(s):
        l=s.p_not()
        while s.lex.at('AND'): s.lex.eat(); l=BinOp(l,'and',s.p_not())
        return l
    def p_not(s):
        if s.lex.at('NOT'): s.lex.eat(); return UnaryOp('not',s.p_not())
        return s.p_cmp()
    def p_cmp(s):
        l=s.p_add()
        while s.lex.at('EQ','NEQ','LT','GT','LE','GE','IN'):
            op=s.lex.eat().value; l=BinOp(l,op,s.p_add())
        return l
    def p_add(s):
        l=s.p_mul()
        while s.lex.at('PLUS','MINUS'):
            op=s.lex.eat().value; l=BinOp(l,op,s.p_mul())
        return l
    def p_mul(s):
        l=s.p_unary()
        while s.lex.at('STAR','SLASH','MOD'):
            op=s.lex.eat().value; l=BinOp(l,op,s.p_unary())
        return l
    def p_unary(s):
        if s.lex.at('MINUS'): s.lex.eat(); return UnaryOp('-',s.p_unary())
        return s.p_postfix()
    def p_postfix(s):
        e=s.p_atom()
        while s.lex.at('DOT','LP'):
            if s.lex.at('DOT'):
                s.lex.eat('DOT')
                m=s.lex.eat()
                if isinstance(e, IdExpr) and e.name=='math':
                    return s._math_call(m.value)
                if isinstance(e, IdExpr) and e.name=='makeset':
                    return s._makeset(m)
                if isinstance(e, IdExpr) and e.name=='input':
                    return s._input_typed(m.value)
                e=BinOp(e,'.',IdExpr(m.value))
            elif s.lex.at('LP'):
                s.lex.eat('LP')
                args=[]
                while not s.lex.at('RP'):
                    args.append(s.parse_expr())
                    if s.lex.at('COMMA'): s.lex.eat('COMMA')
                s.lex.eat('RP')
                if isinstance(e, IdExpr):
                    e=FuncCallExpr(e.name,args)
                else:
                    e=FuncCallExpr(e,args)
        return e

    def _math_call(s, fn):
        if fn=='compute':
            exprs=[]
            while s.lex.at('LP'):
                s.lex.eat('LP'); e=s.parse_expr(); s.lex.eat('RP')
                exprs.append(e)
            return MathComputeExpr(exprs)
        if fn in ('sin','cos','tan'):
            s.lex.eat('LP'); val=s.parse_expr()
            unit='rad'
            if s.lex.at('ID'): unit=s.lex.eat('ID').value
            s.lex.eat('RP')
            return MathTrigExpr(fn,val,unit)
        return FuncCallExpr('math.'+fn,[])

    def _makeset(s, tok):
        if tok.type=='DOT':
            pass
        if s.lex.at('LB'):
            elems=s.parse_list_literal()
            return MakesetExpr(ListLit(elems))
        e=s.parse_expr()
        return MakesetExpr(e)

    def _input_typed(s, typ):
        s.lex.eat('LP'); prompt=s.parse_expr(); s.lex.eat('RP')
        return InputExpr(prompt,typ)

    def p_atom(s):
        t=s.lex.peek()
        if t.type=='NUM': s.lex.eat(); return NumLit(t.value)
        if t.type=='STR': s.lex.eat(); return StrLit(t.value)
        if t.type=='BOOL': s.lex.eat(); return BoolLit(t.value=='true')
        if t.type=='CV': s.lex.eat(); return CVExpr()
        if t.type=='LP':
            s.lex.eat('LP'); e=s.parse_expr(); s.lex.eat('RP'); return e
        if t.type=='LB':
            return ListLit(s.parse_list_literal())
        if t.type=='LC':
            return s._parse_dic_literal()
        if t.type=='DEPSEARCH':
            return s._parse_depsearch()
        if t.type=='MAKESET':
            s.lex.eat('MAKESET'); s.lex.eat('DOT')
            if s.lex.at('LB'):
                return MakesetExpr(ListLit(s.parse_list_literal()))
            return MakesetExpr(s.p_atom())
        if t.type=='INPUT':
            s.lex.eat('INPUT')
            if s.lex.at('DOT'):
                s.lex.eat('DOT'); typ=s.lex.eat('ID').value
                s.lex.eat('LP'); prompt=s.parse_expr(); s.lex.eat('RP')
                return InputExpr(prompt,typ)
            s.lex.eat('LP'); prompt=s.parse_expr(); s.lex.eat('RP')
            return InputExpr(prompt)
        if t.type=='MATH':
            s.lex.eat('MATH'); s.lex.eat('DOT')
            fn=s.lex.eat().value
            return s._math_call(fn)
        if t.type in ('ID',*[k.upper() for k in KEYWORDS if k not in ('true','false','and','or','not','in','CV')]):
            s.lex.eat()
            if s.lex.at('LP'):
                s.lex.eat('LP')
                args=[]
                while not s.lex.at('RP'):
                    args.append(s.parse_expr())
                    if s.lex.at('COMMA'): s.lex.eat('COMMA')
                s.lex.eat('RP')
                return FuncCallExpr(t.value,args)
            return IdExpr(t.value)
        raise SyntaxError(f"Unexpected token {t.type}({t.value!r}) at line {t.line}")

    def _parse_dic_literal(s):
        s.lex.eat('LC'); s.lex.skip_nl()
        pairs=[]
        while not s.lex.at('RC'):
            k=s.parse_expr(); s.lex.eat('COLON'); v=s.parse_expr()
            pairs.append((k,v))
            if s.lex.at('COMMA'): s.lex.eat('COMMA')
            s.lex.skip_nl()
        s.lex.eat('RC')
        return DicLit(pairs)

    def _parse_depsearch(s):
        s.lex.eat('DEPSEARCH')
        name=s.lex.eat('ID').value
        addr=s.parse_list_literal()
        s.lex.eat('RETURN')
        mode=s.lex.eat('ALL','NUM').value
        return DepsearchExpr(name,addr,mode)

# ═══════════════════════════════════════════════════════════════
# ENVIRONMENT & VARIABLE SYSTEM
# ═══════════════════════════════════════════════════════════════
class WaterVar:
    __slots__=('value','kind','typ','owned','moved','borrows','borrow_muts')
    def __init__(s,v,kind='free',typ=None):
        s.value=v;s.kind=kind;s.typ=typ;s.owned=True;s.moved=False
        s.borrows=0;s.borrow_muts=0

class Env:
    def __init__(s, parent=None):
        s.vars={}; s.parent=parent; s.funcs={}
        if parent: s.funcs=parent.funcs
    def get(s, name):
        if name in s.vars:
            v=s.vars[name]
            if v.moved: raise RuntimeError(f"Variable '{name}' has been moved")
            return v
        if s.parent: return s.parent.get(name)
        raise RuntimeError(f"Undefined variable '{name}'")
    def set(s, name, val, kind='free', typ=None):
        s.vars[name]=WaterVar(val,kind,typ)
    def assign(s, name, val):
        if name in s.vars:
            v=s.vars[name]
            if v.moved: raise RuntimeError(f"Variable '{name}' has been moved")
            if v.borrow_muts>0: raise RuntimeError(f"Cannot assign to '{name}' while mutably borrowed")
            if v.kind=='stay' and v.typ:
                val=s._coerce(val,v.typ)
            v.value=val; return
        if s.parent:
            try: s.parent.assign(name,val); return
            except RuntimeError: pass
        s.vars[name]=WaterVar(val)
    def _coerce(s, val, typ):
        m={'int':int,'float':float,'str':str,'string':str,'bool':bool}
        if typ in m:
            try: return m[typ](val)
            except: raise RuntimeError(f"Cannot coerce {val!r} to {typ}")
        return val
    def def_func(s, name, fdef):
        s.funcs[name]=fdef
    def get_func(s, name):
        if name in s.funcs: return s.funcs[name]
        if s.parent: return s.parent.get_func(name)
        raise RuntimeError(f"Undefined function '{name}'")

# ═══════════════════════════════════════════════════════════════
# INTERPRETER
# ═══════════════════════════════════════════════════════════════
class ReturnSignal(Exception):
    def __init__(s,vals): s.vals=vals
class FinSignal(Exception): pass
class GoSignal(Exception): pass
class BackSignal(Exception): pass

TYPE_MAP = {'int':int,'float':float,'str':str,'string':str,'bool':bool}

class Interpreter:
    def __init__(s):
        s.env = Env()
        s.purpose = None
        s.libs = []
        s.unit_convs = {}

    def run(s, program):
        s.exec_stmts(program.stmts, s.env)

    def exec_stmts(s, stmts, env):
        i=0
        while i<len(stmts):
            st=stmts[i]
            if isinstance(st, ErcallStmt):
                if i>0:
                    guarded=stmts[i-1]
                    s._exec_ercall(guarded, st.action, env)
                i+=1; continue
            try:
                s.exec_one(st, env)
            except ReturnSignal: raise
            except FinSignal: raise
            except (GoSignal, BackSignal): raise
            except Exception as e:
                if i+1<len(stmts) and isinstance(stmts[i+1], ErcallStmt):
                    i+=1; continue
                raise
            i+=1

    def _exec_ercall(s, guarded, action, env):
        while True:
            try:
                s.exec_one(guarded, env)
                return
            except (ReturnSignal, FinSignal, GoSignal, BackSignal): raise
            except Exception:
                if action=='go': return
                if action=='fin': raise FinSignal()
                if action=='back': continue

    def exec_one(s, node, env):
        if node is None: return
        m = 'exec_'+type(node).__name__
        fn = getattr(s, m, None)
        if fn: return fn(node, env)
        return s.eval_expr(node, env)

    def exec_UseforStmt(s,n,env): s.purpose=n.purpose
    def exec_SlInportStmt(s,n,env): s.libs.append(n.name)

    def exec_SetStmt(s,n,env):
        kind=n.kind; name=n.name
        if kind=='free':
            v=s.eval_expr(n.val,env) if n.val else None
            env.set(name,v,'free')
        elif kind=='stay':
            v=s.eval_expr(n.val,env) if n.val else None
            if n.typ and v is not None and n.typ in TYPE_MAP:
                v=TYPE_MAP[n.typ](v)
            env.set(name,v,'stay',n.typ)
        elif kind=='dic':
            env.set(name,{},'dic')
        elif kind=='list':
            env.set(name,[],'list',n.typ)
        elif kind=='depthlist':
            env.set(name,[],'depthlist')

    def exec_StaytoStmt(s,n,env):
        v=env.get(n.name); v.typ=n.new_type; v.value=env._coerce(v.value,n.new_type)

    def exec_ListstaytoStmt(s,n,env):
        v=env.get(n.name); v.typ=n.new_type

    def exec_ListOpStmt(s,n,env):
        lst=env.get(n.name).value
        if n.op=='add':
            val=s.eval_expr(n.kw['value'],env)
            items=val if isinstance(val,list) else [val]
            num=n.kw.get('num')
            if num is not None:
                num=int(s.eval_expr(num,env)) if not isinstance(num,(int,float)) else int(num)
                for j,it in enumerate(items): lst.insert(num+1+j,it)
            else:
                lst.extend(items)
        elif n.op=='delete':
            val=s.eval_expr(n.kw['value'],env)
            targets=val if isinstance(val,list) else [val]
            for t in targets:
                while t in lst: lst.remove(t)
        elif n.op=='change':
            num=int(s.eval_expr(n.kw['num'],env))
            old=lst[num] if num<len(lst) else None
            val=s.eval_expr(n.kw['value'],env)
            lst[num]=val

    def exec_DeplistOpStmt(s,n,env):
        dl=env.get(n.name).value
        addr=[int(s.eval_expr(a,env)) if isinstance(a,N) else int(a) for a in n.kw['addr']]
        if n.op=='add':
            target=s._dep_navigate(dl,addr,create=True)
            val=s.eval_expr(n.kw['value'],env)
            items=val if isinstance(val,list) else [val]
            target.extend(items)
        elif n.op=='delete':
            target=s._dep_navigate(dl,addr,create=False)
            if target is not None:
                val=s.eval_expr(n.kw['value'],env)
                targets=val if isinstance(val,list) else [val]
                for t in targets:
                    while t in target: target.remove(t)
        elif n.op=='change':
            parent_addr=addr[:-1]; idx=addr[-1]
            target=s._dep_navigate(dl,parent_addr,create=False)
            if target and idx<len(target):
                val=s.eval_expr(n.kw['value'],env)
                target[idx]=val

    def _dep_navigate(s,dl,addr,create=False):
        cur=dl
        for i,a in enumerate(addr):
            while create and len(cur)<=a:
                cur.append([])
            if a>=len(cur): return None
            if i<len(addr)-1:
                if not isinstance(cur[a],list):
                    if create: cur[a]=[]
                    else: return None
                cur=cur[a]
        return cur

    def exec_IfStmt(s,n,env):
        if s._truthy(s.eval_expr(n.cond,env)):
            s.exec_stmts(n.body,env); return
        for ec,eb in n.elifs:
            if s._truthy(s.eval_expr(ec,env)):
                s.exec_stmts(eb,env); return
        if n.elseb: s.exec_stmts(n.elseb,env)

    def exec_MatchStmt(s,n,env):
        val=s.eval_expr(n.expr,env)
        for pat,body in n.arms:
            if pat=='_':
                s.exec_one(body,env); return
            pv=s.eval_expr(pat,env) if isinstance(pat,N) else pat
            if val==pv:
                s.exec_one(body,env); return

    def exec_PrintStmt(s,n,env):
        v=s.eval_expr(n.expr,env)
        print(v)

    def exec_ClearStmt(s,n,env):
        os.system('cls' if os.name=='nt' else 'clear')

    def exec_RepeatStmt(s,n,env):
        if n.cond_mode:
            while True:
                cv=s._truthy(s.eval_expr(n.count,env))
                if cv==n.cond_val: break
                s.exec_stmts(n.body,env)
        else:
            count=int(s.eval_expr(n.count,env))
            for _ in range(count):
                s.exec_stmts(n.body,env)

    def exec_LetStmt(s,n,env):
        v=s.eval_expr(n.val,env)
        env.set(n.name,v,'free')

    def exec_AssignStmt(s,n,env):
        v=s.eval_expr(n.val,env)
        if n.op=='+=':
            old=env.get(n.name).value; v=old+v
        elif n.op=='-=':
            old=env.get(n.name).value; v=old-v
        env.assign(n.name,v)

    def exec_FuncDef(s,n,env):
        env.def_func(n.name, n)

    def exec_ReturnStmt(s,n,env):
        vals=[s.eval_expr(v,env) for v in n.vals]
        raise ReturnSignal(vals)

    def exec_WaitStmt(s,n,env):
        sec=s.eval_expr(n.sec,env)
        time.sleep(float(sec))

    def exec_MoveStmt(s,n,env):
        src=env.get(n.src)
        if src.borrows>0 or src.borrow_muts>0:
            raise RuntimeError(f"Cannot move '{n.src}' while borrowed")
        env.set(n.dst, src.value, src.kind, src.typ)
        src.moved=True

    def exec_BorrowStmt(s,n,env):
        src=env.get(n.src)
        if n.mut:
            if src.borrows>0 or src.borrow_muts>0:
                raise RuntimeError(f"Cannot borrow_mut '{n.src}' while already borrowed")
            src.borrow_muts+=1
            env.set(n.dst, src.value, src.kind, src.typ)
        else:
            if src.borrow_muts>0:
                raise RuntimeError(f"Cannot borrow '{n.src}' while mutably borrowed")
            src.borrows+=1
            env.set(n.dst, src.value, src.kind, src.typ)

    def exec_ScopeBlock(s,n,env):
        child=Env(env)
        s.exec_stmts(n.body, child)
        for name,var in child.vars.items():
            if name in env.vars:
                src_var=env.vars[name]
                if src_var.borrows>0: src_var.borrows-=1
                if src_var.borrow_muts>0: src_var.borrow_muts-=1

    def exec_UnitConvStmt(s,n,env):
        d=s.eval_expr(n.defn,env) if isinstance(n.defn,N) else n.defn
        s.unit_convs[str(d)]=True

    def exec_ErcallStmt(s,n,env): pass

    # ── Expression evaluator ──
    def eval_expr(s, node, env):
        if node is None: return None
        m='eval_'+type(node).__name__
        fn=getattr(s,m,None)
        if fn: return fn(node,env)
        raise RuntimeError(f"Cannot evaluate {type(node).__name__}")

    def eval_NumLit(s,n,env): return n.value
    def eval_StrLit(s,n,env): return n.value
    def eval_BoolLit(s,n,env): return n.value
    def eval_IdExpr(s,n,env): return env.get(n.name).value
    def eval_CVExpr(s,n,env): return env.get('CV').value
    def eval_ListLit(s,n,env): return [s.eval_expr(e,env) for e in n.elems]
    def eval_DicLit(s,n,env): return {s.eval_expr(k,env):s.eval_expr(v,env) for k,v in n.pairs}

    def eval_BinOp(s,n,env):
        if n.op=='.':
            l=s.eval_expr(n.left,env)
            if isinstance(n.right,IdExpr): return l[n.right.name] if isinstance(l,dict) else getattr(l,n.right.name)
        l=s.eval_expr(n.left,env)
        r=s.eval_expr(n.right,env)
        ops={'+':lambda a,b:a+b, '-':lambda a,b:a-b, '*':lambda a,b:a*b,
             '/':lambda a,b:a/b, '%':lambda a,b:a%b,
             '==':lambda a,b:a==b, '!=':lambda a,b:a!=b,
             '<':lambda a,b:a<b, '>':lambda a,b:a>b,
             '<=':lambda a,b:a<=b, '>=':lambda a,b:a>=b,
             'and':lambda a,b:a and b, 'or':lambda a,b:a or b,
             'in':lambda a,b:a in b}
        if n.op in ops: return ops[n.op](l,r)
        raise RuntimeError(f"Unknown operator {n.op}")

    def eval_UnaryOp(s,n,env):
        v=s.eval_expr(n.expr,env)
        if n.op=='-': return -v
        if n.op=='not': return not v

    def eval_InputExpr(s,n,env):
        prompt=s.eval_expr(n.prompt,env) if n.prompt else ''
        val=input(str(prompt))
        if n.typ and n.typ in TYPE_MAP:
            try: val=TYPE_MAP[n.typ](val)
            except: pass
        return val

    def eval_DepsearchExpr(s,n,env):
        dl=env.get(n.name).value
        addr=[int(s.eval_expr(a,env)) if isinstance(a,N) else int(a) for a in n.addr]
        cur=dl
        for a in addr:
            if a<len(cur) and isinstance(cur[a],list): cur=cur[a]
            elif a<len(cur): return cur[a]
            else: return None
        if n.mode=='num':
            return [x for x in cur if not isinstance(x,list)]
        return copy.deepcopy(cur)

    def eval_MakesetExpr(s,n,env):
        v=s.eval_expr(n.src,env)
        if isinstance(v,list): return ''.join(str(x) for x in v)
        return str(v)

    def eval_MathComputeExpr(s,n,env):
        cv=0
        for expr in n.exprs:
            env.set('CV',cv,'free')
            cv=s.eval_expr(expr,env)
        return cv

    def eval_MathTrigExpr(s,n,env):
        val=s.eval_expr(n.val,env)
        u=n.unit
        if u=='deg': val=val*math.pi/180
        elif u=='grad': val=val*math.pi/200
        elif u=='turn': val=val*2*math.pi
        elif u=='mil': val=val*2*math.pi/6400
        fn={'sin':math.sin,'cos':math.cos,'tan':math.tan}
        return fn[n.func](val)

    def eval_FuncCallExpr(s,n,env):
        try:
            fdef=env.get_func(n.name)
        except RuntimeError:
            raise RuntimeError(f"Undefined function '{n.name}'")
        args=[s.eval_expr(a,env) for a in n.args]
        if fdef.kind in ('frcall','frcallend'):
            child=Env(env)
        else:
            child=Env()
            child.funcs=env.funcs
        for p,a in zip(fdef.params, args):
            child.set(p,a,'free')
        for vs in fdef.vsets:
            if vs.dir=='in':
                child.set(vs.intr, env.get(vs.ext).value,'free')
            elif vs.dir=='out':
                pass
        def run_func():
            try:
                s.exec_stmts(fdef.body, child)
            except ReturnSignal as rs:
                return rs.vals
            return []
        if fdef.kind in ('call','frcall'):
            t=threading.Thread(target=run_func)
            t.start()
            return None
        else:
            try:
                s.exec_stmts(fdef.body, child)
            except ReturnSignal as rs:
                for vs in fdef.vsets:
                    if vs.dir=='out':
                        env.assign(vs.ext, child.get(vs.intr).value)
                vals=rs.vals
                if len(vals)==1: return vals[0]
                if len(vals)>1: return vals
                return None
            for vs in fdef.vsets:
                if vs.dir=='out':
                    env.assign(vs.ext, child.get(vs.intr).value)
            return None

    def eval_InExpr(s,n,env):
        v=s.eval_expr(n.val,env)
        c=s.eval_expr(n.container,env)
        return v in c

    def _truthy(s,v):
        if v is None: return False
        if isinstance(v,bool): return v
        if isinstance(v,(int,float)): return v!=0
        if isinstance(v,str): return len(v)>0
        if isinstance(v,list): return len(v)>0
        return True

# ═══════════════════════════════════════════════════════════════
# REPL & MAIN
# ═══════════════════════════════════════════════════════════════
def run_source(src, interp=None):
    if interp is None: interp=Interpreter()
    lex=Lexer(src)
    parser=Parser(lex)
    prog=parser.parse()
    try:
        interp.run(prog)
    except FinSignal:
        pass
    return interp

def main():
    if len(sys.argv)>=2:
        fname=sys.argv[1]
        with open(fname,'r',encoding='utf-8') as f:
            src=f.read()
        try:
            run_source(src)
        except FinSignal:
            pass
        except Exception as e:
            print(f"Error: {e}",file=sys.stderr)
            sys.exit(1)
    else:
        print("Water Language REPL v1.0")
        print("Type 'exit' to quit.\n")
        interp=Interpreter()
        buf=''
        brackets=0
        while True:
            try:
                prompt='water> ' if not buf else '  ...> '
                line=input(prompt)
            except (EOFError,KeyboardInterrupt):
                print(); break
            if line.strip()=='exit' and not buf:
                break
            buf+=line+'\n'
            brackets+=line.count('[')-line.count(']')
            brackets+=line.count('{')-line.count('}')
            if line.rstrip().endswith(':') or brackets>0:
                continue
            try:
                interp=run_source(buf,interp)
            except FinSignal:
                break
            except Exception as e:
                print(f"Error: {e}")
            buf=''; brackets=0

if __name__=='__main__':
    main()
