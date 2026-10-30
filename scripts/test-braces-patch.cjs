const assert = require('node:assert/strict');
const test = require('node:test');
const braces = require('braces');
test('ordinary expansion, compilation, quoted and escaped braces stay compatible', () => {
  assert.deepEqual(braces.expand('x/{a,b}/{1..3}'), ['x/a/1','x/a/2','x/a/3','x/b/1','x/b/2','x/b/3']);
  assert.equal(braces.compile('x/{a,b}'), 'x/(a|b)');
  assert.equal(braces.stringify(braces.parse('x/{a,b}')), 'x/{a,b}');
  assert.equal(braces.compile('a'.repeat(9000)), 'a'.repeat(9000));
  assert.deepEqual(braces.expand('"{literal}"'), ['{literal}']);
  assert.equal(braces.compile('\\{literal\\}'), '{literal}');
});
test('deep braces and parentheses reject before recursive walkers, balanced or unfinished', () => {
  for (const [open,close] of [['{','}'],['(',')']]) {
    for (const suffix of [close.repeat(3000),'']) {
      const input=open.repeat(3000)+'a,b'+suffix;
      for (const fn of [braces.parse,braces.compile,braces.expand,braces.stringify]) {
        assert.throws(() => fn(input), { name:'SyntaxError', message:/safe nesting/ });
      }
    }
  }
});
test('direct AST input cannot bypass depth and cycle validation', () => {
  let ast={type:'text',value:'x'};
  for(let i=0;i<6000;i++) ast={type:'root',nodes:[ast]};
  const cycle={type:'root',nodes:[]};cycle.nodes.push(cycle);
  for(const fn of [braces.compile,braces.expand,braces.stringify]) {
    for(const input of [ast,cycle]) assert.throws(() => fn(input), {name:'SyntaxError',message:/safe nesting/});
  }
});

test('patched brace expansion supports legacy and current CommonJS consumers', () => {
  const expand = require('brace-expansion');
  assert.deepEqual(expand('a{b,c}'), ['ab','ac']);
  assert.deepEqual(expand.expand('a{b,c}'), ['ab','ac']);
  const legacy = require('minimatch');
  assert.equal(legacy('ab', 'a{b,c}'), true);
  assert.equal(legacy('ax', 'a{b,c}'), false);
});
