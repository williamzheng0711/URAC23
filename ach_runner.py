from optparse import OptionParser
import numpy as np
import time
from utils import *
from slow_lib import *
from ach_utils import *
from tc_utils import *
from ldpc_utils import *


parser = OptionParser()
parser.add_option("--args", type="string", dest="args", help="Arguments", default="")
parser.add_option("--ka", type="int", dest="ka", help="Number of active users", default=-1)
parser.add_option("--pe", type="float", dest="pe", help="Probability of being erased (mapped to 0)", default=-1)
(options, args) = parser.parse_args()

p_e = options.pe
assert p_e >= 0
K = options.ka                                      # number of active users
assert K > 0 

# Other parameter settings. No need to change at this moment.
w = 128                                             # Length of each user's uncoded message (total number of info bits)
L = 16                                              # Number of sections
assert w % L ==0


### My (outer) code setting
###
parityLen = 8
assert (w+L*parityLen) % L ==0
J = int((w + L*parityLen)/L)                             # Length of each coded sub-block
messageLen = int(J - parityLen)
assert messageLen * L == w
M = 2**J                                            # Each coded sub-block is J-length binary, 
                                                        # to represent it in decimal, 
                                                        # it ranges in [0, M] = [0, 2**J].
windowSize = 2                                      # How many previous sections p(j) depends on
assert windowSize > 0
Pa = L*parityLen                                    # Total number of parity check bits, in this case Pa=w=128
listSize = K                                        # list size retained per section after AMP converges
parityInvolved = get_parity_involvement_matrix(L,windowSize,messageLen)    
                                                        # An L x L matrix.
                                                        # For each row i, the j-th entry = w/L(=8), iff, w(i) involves the construction of p(j). 
                                                        # E.g., parityInvolved[0] = [0,8,8,8,8,0,0,0,0,0,0,0,0,0,0,0]
whichGMatrix = get_G_matrices(parityInvolved)        # An L x L matrix. Only (i,j) s.t. parityInvolved[i][j]!=0 matters.
                                                        # For (i,j) of our interest, 
                                                        # whichGMatrix[i][j] returns a code (an index) for some specific G_{i,j} matrix.
                                                        # Where G_{i,j} matrix is the parity generating matrix needed to 
                                                        # calculate the contribution of w(i) while calculating p(j)
whichGMatrix_or = whichGMatrix.copy()


### Tree (outer) code setting 
###
### This is obtained from the Opt_prob.m file
parityLengthVector = np.array([0, 6, 8,8,8,8,8,8,8,8,8,8,8,8, 10, 16],dtype=int) # Parity bits distribution

J=((w+np.sum(parityLengthVector))/L).astype(int) # Length of each coded sub-block
M=2**J # Length of each section
messageLengthVector = np.subtract(J*np.ones(L, dtype = 'int'), parityLengthVector).astype(int)
Pa = np.sum(parityLengthVector) # Total number of parity check bits
Ml = np.sum(messageLengthVector) # Total number of information bits
G = generate_parity_matrix(L,messageLengthVector,parityLengthVector)




print("####### Start Rocking ######## K=" + str(K) +" and p_e= " + str(p_e))          # Simulation starts!!!!!
# Outer-code encoding. No need to change.
txBits = np.random.randint(low=2, size=(K, w))   

# LLC: Generate random binary messages for K active users. Hence txBits.shape is [K,w]
txBitsParitized_llc = slow_encode(txBits,K,L,J,Pa,w,messageLen,parityLen,parityInvolved,whichGMatrix) 
tx_symbols_llc = ach_binary_to_symbol(txBitsParitized_llc, L, K, J)

# Tree Code: Encode and from binary to symbols
txBitsParitized_tc = Tree_encode(txBits,K,G,L,J,Pa,Ml,messageLengthVector,parityLengthVector)
tx_symbols_tc = ach_binary_to_symbol(txBitsParitized_tc, L, K, J)

# LDPC: Get encoded symbols
outer_code = FGG.Triadic8(16)
tx_symbols_ldpc, user_codewords = LDPC_encode_to_symbol(txBits, L, K, J, outer_code)


# * A-Channel with Erasure
seed = np.random.randint(0,10000)
rx_coded_symbols_llc, num_one_outage, one_outage_where, num_no_outage = ach_with_erasure(tx_symbols_llc, L, K, J, p_e, seed=seed)
rx_coded_symbols_llc_or = rx_coded_symbols_llc.copy()
print("Genie: How many no-outage ? " + str(num_no_outage))
print("Genie: How many one-outage? " + str(num_one_outage))
print("Genie: One-outage where: " + str(one_outage_where))
rx_coded_symbols_tc, _, _, _  = ach_with_erasure(tx_symbols_tc,  L, K, J, p_e, seed=seed)
rx_coded_symbols_ldpc, _, _, _ = ach_with_erasure(tx_symbols_ldpc,L, K, J, p_e, seed=seed)



# *Outer code decoder. 
## LLC
print(" -- Decoding now starts.")
tic = time.time()
rxBits_llc = llc_UACE_decoder(rx_coded_symbols_llc, L, J, messageLen, parityLen, listSize, parityInvolved, whichGMatrix, windowSize, APlus=False)
toc = time.time()
print(" | Time of LLC decoding " + str(toc-tic))
rxBits_llc = np.unique(rxBits_llc, axis=0)
if rxBits_llc.shape[0] > K: 
    rxBits_llc = rxBits_llc[np.arange(K)] 

## Tree Code
tic = time.time()
cs_decoded_tc = Tree_symbols_to_bits(listSize, L, J, rx_coded_symbols_tc)
rxBits_tc = Tree_decoder(cs_decoded_tc,G,L,J,w,parityLengthVector,messageLengthVector,listSize)
toc = time.time()
print(" | Time of Tree Code decode " + str(toc-tic))
if rxBits_tc.shape[0] > K: 
    rxBits_tc = rxBits_tc[np.arange(K)] 

## LDPC
tic = time.time()
unioned_cdwds_ldpc = LDPC_symbols_to_bits(L, J, rx_coded_symbols_ldpc, K, "A-Channel")
rx_user_codewords = outer_code.decoder(unioned_cdwds_ldpc, K)
rx_user_codewords = np.array(rx_user_codewords)
toc = time.time()
print(" | Time of LDPC Code decode " + str(toc-tic))


# Check how many are correct amongst the recover. No need to change.
## LLC
_ = check(txBits, rxBits_llc, "Linked-loop Code", 1)
## Tree code
_ = check(txBits, rxBits_tc, "Tree Code", 1)
## LDPC code
LDPC_num_matches = FGG.numbermatches(user_codewords, rx_user_codewords, K)
print(f' | LDPC decodes {LDPC_num_matches}/{len(rx_user_codewords)} codewords. ')
