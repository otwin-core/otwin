# ClusterFuzzLite build image.
#
# Scorecard's Fuzzing check looks for this file; its real job is to give the
# fuzzing engine a container where otwin and Atheris are installed and the
# targets can be built.
FROM gcr.io/oss-fuzz-base/base-builder-python@sha256:6b2b3a7e4a2da50de47f94925cffbe34747e1aae4f33d7f07ba6c681dd648b23

RUN apt-get update && apt-get install -y --no-install-recommends \
        libatomic1 \
    && rm -rf /var/lib/apt/lists/*

COPY . $SRC/otwin
WORKDIR $SRC/otwin
COPY .clusterfuzzlite/build.sh $SRC/build.sh
