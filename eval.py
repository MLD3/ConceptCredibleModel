import argparse
import os

def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=['ccm', 'cbm', 'ccmr', 'std'],
                        help="ccm or cbm or ccmr or std")
    parser.add_argument("o", help="where's the model directory eg. outputs/tid/")
    parser.add_argument("-s", "--shortcut",
                        default="outputs/aca36656e58e11ebb773ac1f6b24a434/cbm.pt",
                        help="which cbm to create the shortcut")
    parser.add_argument("-n", "--n_shortcuts", default=10, type=int,
                        help="number of shortcuts")
    args = parser.parse_args()
    print(args)
    return args


if __name__ == '__main__':
    flags = get_args()

    base_command = ['python',
                    {'ccm': 'scripts/ccm.py',
                     'cbm': 'scripts/cbm.py',
                     'ccmr': 'scripts/ccm_r.py',
                     'std': 'scripts/standard_model.py'
                    }[flags.mode],
                    '--eval',
                    '-o', flags.o,
                    '--n_shortcuts', str(flags.n_shortcuts)]

    for shortcut in ['clean', 'noise', flags.shortcut]:
        print({'clean': 'clean acc',
               'noise': 't=0 acc',
               flags.shortcut: 't=1 acc'}[shortcut])
        
        command = base_command + ['-s', shortcut]
        if shortcut == 'noise':
            command += ['-t', '0']
        else:
            command += ['-t', '1']

        command = " ".join(command)
        print(command)
        
        os.system(command)    
        
        