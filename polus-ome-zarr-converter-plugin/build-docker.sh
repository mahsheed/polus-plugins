#!/bin/bash

version=$(<VERSION)
docker build . -t labshare/polus-ome-zarr-converter-plugin:${version}