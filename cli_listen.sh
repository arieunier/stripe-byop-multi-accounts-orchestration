#!/bin/bash
# Usage: ./cli_listen.sh <alias> <api_key>
# Example: ./cli_listen.sh US sk_test_51Sma9NPm0A0XhmmQtJCZIOuuSGt3WFgH6oQvjcH83AQneCjr8qROpRXSB3ZyISqtMeFbiiudOSUpwIycwxCsYNEN00Osy71uFT
# Example: ./cli_listen.sh EU sk_test_51Sma9NPm0A0XhmmQtJCZIOuuSGt3WFgH6oQvjcH83AQneCjr8qROpRXSB3ZyISqtMeFbiiudOSUpwIycwxCsYNEN00Osy71uFT

alias=$1
api_key=$2

if [ -z "$alias" ] || [ -z "$api_key" ]; then
    echo "Usage: ./cli_listen.sh <alias> <api_key>"
    exit 1
fi
stripe listen --api-key $api_key --forward-to localhost:5000/webhook/$alias