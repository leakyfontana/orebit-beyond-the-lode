using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class ExitShopDoorCollision : MonoBehaviour
{
    public GameObject linked_door;
	public Collider2D player_collision;
	
	//Upon collision with another GameObject, this GameObject will reverse direction
    private void OnTriggerExit2D(Collider2D other)
    {
		if(other == player_collision){
			linked_door.SetActive(true);
			Debug.Log("Exiting collision");
		}
    }
}
