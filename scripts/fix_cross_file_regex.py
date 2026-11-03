with open('core/cross_file_contract.py', 'r', encoding='utf-8') as f:
    txt = f.read()

lines = txt.split('\n')
for idx, l in enumerate(lines):
    if 'for cm in re.findall' in l:
        print('Line:', idx+1, repr(l))
        lines[idx] = '                for cm in re.findall(r\'class=["\\\']([^"\\\']+)["\\\']\', html_txt):'

with open('core/cross_file_contract.py', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print('Successfully fixed regex in core/cross_file_contract.py')
