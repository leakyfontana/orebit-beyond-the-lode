using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class ShopDoorCollision : MonoBehaviour
{
	public GameObject player;
	public GameObject linked_shop_object; 
	public Collider2D player_collision;
	public GameObject ui_manager;
	
	//Upon collision with another GameObject, this GameObject will reverse direction
    private void OnTriggerEnter2D(Collider2D other)
    {
		if(other == player_collision && !ui_manager.GetComponent<UIManager>().isUIOpen()){
			FindObjectOfType<AudioManager>().PlayMusic("ShopMusic");
			linked_shop_object.SetActive(true);
			gameObject.SetActive(false);
			Debug.Log("Entering shop collision");
		}
    }
}
