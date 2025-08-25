using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.EventSystems;

public class CancelMouseMovementOnMouseHover : MonoBehaviour
{
	public GameObject player;
    void OnMouseOver()
    {
        //If your mouse hovers over the GameObject with the script attached, output this message
        Debug.Log("Mouse is over GameObject.");
		player.GetComponent<PlayerMovement>().can_use_mouse_control = false;
    }

    void OnMouseExit()
    {
        //The mouse is no longer hovering over the GameObject so output this message each frame
        Debug.Log("Mouse is no longer on GameObject.");
		player.GetComponent<PlayerMovement>().can_use_mouse_control = true;
    }
}
