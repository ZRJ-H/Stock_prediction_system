import numpy as np
from scipy import stats
import importlib
from pathlib import Path
import pandas as pd
from sklearn.preprocessing import minmax_scale
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder
import os

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
tf = importlib.import_module('tensorflow.compat.v1')
tf.disable_v2_behavior()

# 读取数据集
df = pd.read_csv(Path("dataset") / "tt.csv")
# 数据归一化
df['open'] = minmax_scale(df['open'])
df['high'] = minmax_scale(df['high'])
df['low'] = minmax_scale(df['low'])

# 构建向量矩阵
# 总数据矩阵/标签
data = []
label = []


# 定义窗口函数
def windows(data, size):
    start = 0
    while start < data.count():
        yield int(start), int(start + size)
        start += (size / 2)


# 返回格式数据
def segment_signal(data, window_size=90):
    segments = np.empty((0, window_size, 3))
    labels = np.empty((0))
    for (start, end) in windows(data["timestamp"], window_size):
        x = data["open"][start:end]
        y = data["high"][start:end]
        z = data["low"][start:end]
        if (len(df["timestamp"][start:end]) == window_size):
            segments = np.vstack([segments, np.dstack([x, y, z])])
            labels = np.append(labels, stats.mode(data["label"][start:end])[0][0])
    return segments, labels


data, label = segment_signal(df)
# 对标签数据进行处理
for i in range(0, len(label)):
    if label[i] == -1:
        label[i] = 0

#将数据集按照8:2划分为训练集和测试集
X_train, X_test, y_train, y_test = train_test_split(data, label, test_size=0.2)
X_train = np.array(X_train).reshape(len(X_train), 90, 3)
X_test = np.array(X_test).reshape(len(X_test), 90, 3)
y_train = np.array(y_train).reshape(-1, 1)
y_test = np.array(y_test).reshape(-1, 1)

# 涨跌标签采用独热编码（One-Hot）
enc = OneHotEncoder()
enc.fit(y_train)
y_train = enc.transform(y_train).toarray()
y_test = enc.transform(y_test).toarray()

#通道数量为3个
in_channels = 3

#训练迭代次数
epoch = 10000
#定义批大小
batch_size = 5
batch = X_train.shape[0] / batch_size

# 创建占位符
X = tf.placeholder(tf.float32, shape=(None, 90, in_channels))
Y = tf.placeholder(tf.float32, shape=(None, 2))

# 第一层
h1 = tf.layers.conv1d(X, 256, 4, 2, 'SAME', name='h1', use_bias=True, activation=tf.nn.relu)
p1 = tf.layers.max_pooling1d(h1, 2, 2, padding='VALID')
print(h1)
print(p1)

# 第二层
h2 = tf.layers.conv1d(p1, 256, 4, 2, 'SAME', use_bias=True, activation=tf.nn.relu)
p2 = tf.layers.max_pooling1d(h2, 2, 2, padding='VALID')
print(h2)
print(p2)

# 第三层
h3 = tf.layers.conv1d(p1, 2, 4, 2, 'SAME', use_bias=True, activation=tf.nn.relu)
p3 = tf.layers.max_pooling1d(h3, 11, 1, padding='VALID')
res = tf.reshape(p3, shape=(-1, 2))

print(h3)
print(p3)
print(res)

#定义损失函数
loss = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits_v2(logits=res, labels=Y))

# 定义正确率评价指标
ac = tf.cast(tf.equal(tf.argmax(res, 1), tf.argmax(Y, 1)), tf.float32)
acc = tf.reduce_mean(ac)

# 创建优化器
optim = tf.train.AdamOptimizer(0.0001).minimize(loss)

#执行训练
with tf.Session() as sess:
    sess.run(tf.global_variables_initializer())
    for i in range(epoch):
        sess.run(optim, feed_dict={X: X_train, Y: y_train})
        if i % 100 == 0:
            los, accuracy = sess.run([loss, acc], feed_dict={X: X_train, Y: y_train})
            print(los, accuracy)
    #应用测试集测试
    ccc = sess.run(tf.argmax(res, 1), feed_dict={X: X_test, Y: y_test})
    #输出测试结果
    print(ccc)

