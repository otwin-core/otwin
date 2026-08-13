# ClusterFuzzLite build image.
#
# Scorecard's Fuzzing check looks for this file; its real job is to give the
# fuzzing engine a container where otwin and Atheris are installed and the
# targets can be built.
FROM gcr.io/oss-fuzz-base/base-builder-python

RUN apt-get update && apt-get install -y --no-install-recommends \
        libatomic1 \
    && rm -rf /var/lib/apt/lists/*

COPY . $SRC/otwin
WORKDIR $SRC/otwin
COPY .clusterfuzzlite/build.sh $SRC/build.sh
