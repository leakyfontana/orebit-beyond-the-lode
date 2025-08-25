using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class PlayerAttackBehavior : MonoBehaviour
{
    public int damage;
	
	void OnTriggerEnter2D(Collider2D col){
		if (col.gameObject.tag == "BossP1"){
		print("Boss entered attack");
			col.gameObject.GetComponent<P1BossMethods>().loseHP(damage);
		}
		else if (col.gameObject.tag == "BossP2"){
		print("Boss entered attack");
			col.gameObject.GetComponent<P2BossMethods>().loseHP(damage);
		}
	}
}
