*** Settings ***
Resource    ../../resources/orders.resource

*** Test Cases ***
Cancel Unpaid Order
    [Tags]    OIE-123    OIE-140
    Create Unpaid Order
    Cancel Order
    Order Should Be Cancelled
