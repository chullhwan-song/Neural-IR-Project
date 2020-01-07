import tensorflow as tf
import os

yp_name = "doc_rel:0"
yn_name = "doc_nrel:0"
out_name = "output:0"
loss_name = "Mean:0"
opt_name = "sgd_opt"

'''
This is our implementation of the PACRR network (arXiv:1704.03940 [cs.IR])
'''

# saves the network
def save(sess, file, saver):
    saver.save(sess, file)


# loads the network
def load(sess, file):
    saver = tf.train.import_meta_graph("%s.meta" % file)
    saver.restore(sess, tf.train.latest_checkpoint(os.path.dirname(file)))

    graph = tf.get_default_graph()

    tnames = [loss_name, yp_name, yn_name, out_name]
    onames = [opt_name]

    outs = []
    for n in tnames:
        outs.append(graph.get_tensor_by_name(n))

    for n in onames:
        outs.append(graph.get_operation_by_name(n))

    outs.append(saver)

    return tuple(outs)


# Get main part of network.
# since we need to insert two scripts for training, variable reusing is required.
#   lq = 10
#   ld = 20
#   lf = 32 > tf.layers.conv2d's output channel
#   lg = 3
# x_r : (-1, lq, ld, 1) > query & doc 사이의 term relation (similarity?) matrix
def get_doc_graph(x_r, lq, ld, lf, lg, denses, reuse=True, name_appx="", k=3):
    if name_appx != "":
        name_appx = "_" + name_appx

    poses = [ld]

    reuse_mode = tf.AUTO_REUSE if reuse else None

    kmaxpools = []
    for i in range(1, lg + 1): # kernel size > increasing...
        dim_name = "%dx%d%s" % (i, i, name_appx)
        conv = tf.layers.conv2d(x_r, lf, kernel_size=(i, i), strides=(1, 1), padding="same", use_bias=True,
                                activation=tf.nn.relu, kernel_initializer=tf.glorot_uniform_initializer(),
                                reuse=reuse_mode, name="conv_"+dim_name)

        
        # ?? (-1, lq, ld, lf) >  (-1, lq, lf, ld) > max pooling하게 위해 이렇게 ...
        conv = tf.transpose(conv, perm=(0, 1, 3, 2)) 
        # ?? (-1, lq, lf, ld) > max_pooling2d >  (-1, lq, 1, ld)          
        pool = tf.layers.max_pooling2d(conv, pool_size=(1, lf), strides=(1, lf), padding="valid",  name="maxpool2d_"+dim_name)
        # 개인적으론 위에 tf.transpose 하지않고, channel 개념 max pooling > nput = tf.reduce_max( conv, [1, 2], name='pool') > 요거랑 다른게 몰까??

        
        pool = tf.reshape(pool, (-1, lq, ld))
         
        # ? poses >  poses[0] = ld 
        # ?? k > top k
        # 각 lq > pool'ld(=20) 중 top k
        kmaxpool = tf.nn.top_k(tf.slice(pool, [0, 0, 0], [-1, -1, poses[0]]), k=k, sorted=True)[0]
        # 주의) kmaxpool의 0(=kmaxpool[0]) 이니, top 1만...이 아니라..
        # val, idx 을 리턴하는데, val 만 취하겠다는 의미.!!!!
        
        kmaxpools.append(kmaxpool)

    pooled = tf.concat(kmaxpools, -1)
    dense = tf.layers.flatten(pooled)

    for idx, i in enumerate(denses):
        dense = tf.layers.dense(dense, i, tf.nn.relu, reuse=reuse_mode, name="dense_n%d%s" % (idx, name_appx))
     
    # ?? dense = [-1, lqxlg]
    # output = 1 > 이게 final ranking score    
    #  [-1, lqxlg] >  [-1, 1]
    dout = tf.layers.dense(dense, 1, reuse=reuse_mode, name="dense_out%s" % name_appx)
    #    [-1, lqxlg] > [-1, 1] > [-1] # 각 batch 별 score가 나옴.
    out = tf.squeeze(dout, axis=1, name="output"+name_appx)
    return out

# build our network
# train.ipynb에서 호출
#   lq = 10
#   ld = 20
#   lf = 32 > tf.layers.conv2d's output channel
#   lg = 3
#   k = 3
#   lr = 0.01
def build(lq, ld, lf, lg, k=3, denses=[32, 32], lr=0.01, opt='sgd'):
    # placeholders for positive and negative doc similarity matrices
    yp = tf.placeholder(tf.float32, (None, lq, ld), name=yp_name)
    yn = tf.placeholder(tf.float32, (None, lq, ld), name=yn_name)

    #reshape for CNN
    yp_r = tf.reshape(yp, (-1, lq, ld, 1))
    yn_r = tf.reshape(yn, (-1, lq, ld, 1))

    # get computation graph for each doc matrix (WITH VARIABLE REUSE)
    prel = get_doc_graph(yp_r, lq, ld, lf, lg, denses, k=k, reuse=True)
    nrel = get_doc_graph(yn_r, lq, ld, lf, lg, denses, k=k, reuse=True)

    # Softmax on output
    loss_top = tf.exp(prel)
    loss_logits = loss_top / (loss_top + tf.exp(nrel))

    # Mean binary cross-entropy
    loss = tf.nn.sigmoid_cross_entropy_with_logits(logits=loss_logits, labels=tf.ones(tf.shape(prel), dtype=tf.float32))
    loss = tf.reduce_mean(loss)
    #loss = tf.multiply(-1.0, tf.log(loss_logits), name=loss_name)

    # Use SGD or Adam optimizer
    if opt == 'sgd':
        opt = tf.train.GradientDescentOptimizer(lr).minimize(loss, name=opt_name)
    else:
        opt = tf.train.AdamOptimizer(learning_rate=lr).minimize(loss, name=opt_name)

    saver = tf.train.Saver()

    return yp, yn, prel, loss, opt, saver
